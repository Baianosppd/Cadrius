"""API do assistente (CAD-221). Prefixo /api/v1/assistant/. Cada pessoa só vê as próprias conversas."""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from aigov import llm
from assistant import engine
from assistant.models import Conversation, PendingAction
from assistant.tools import TOOLS


def action_json(a: PendingAction) -> dict:
    tool = TOOLS.get(a.tool)
    return {'id': a.pk, 'ferramenta': a.tool, 'rotulo': tool.label if tool else a.tool, 'resumo': a.summary, 'argumentos': a.arguments,
            'status': a.status, 'resultado': a.result, 'criada_em': a.created_at, 'decidida_em': a.decided_at,
            'mensagem_id': a.message_id}


def conv_json(c: Conversation, full=False) -> dict:
    data = {'id': c.pk, 'titulo': c.title or 'Nova conversa', 'atualizada_em': c.updated_at}
    if full:
        data['mensagens'] = [{'id': m.pk, 'papel': m.role, 'texto': m.content, 'provedor': m.provider, 'ferramentas': m.tools,
                              'criada_em': m.created_at} for m in c.messages.all()]
        data['acoes'] = [action_json(a) for a in c.actions.all()]
    return data


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def ctx(self, request):
        m = get_active_membership(request.user)
        if m is None:
            return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        return engine.Ctx(org=m.organization, user=request.user, role=m.role), None

    def conv(self, ctx, pk):
        return Conversation.objects.filter(pk=pk, organization=ctx.org, user=ctx.user).first()


class StatusView(_Base):
    """O assistente está disponível? (provedores seguros para dado do escritório, sem expor chaves)."""

    def get(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        from aigov.guard import get_policy, global_ai_enabled
        policy = get_policy(ctx.org)
        allowed = policy.allowed_providers or []
        seguros = llm.candidates(allowed, sensitive=True, need_tools=True, profile='assistente')
        return Response({'disponivel': bool(seguros) and policy.ai_enabled and global_ai_enabled(), 'provedores': seguros,
                         'ia_ligada': policy.ai_enabled and global_ai_enabled(), 'pode_agir': ctx.role in engine.WRITE_ROLES,
                         'escrita': sorted(engine.WRITING), 'ferramentas': [{'nome': t.name, 'rotulo': t.label, 'acao': t.action}
                                                                            for t in TOOLS.values()]})


class ConversationListView(_Base):
    def get(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        rows = Conversation.objects.filter(organization=ctx.org, user=ctx.user)[:50]
        return Response([conv_json(c) for c in rows])

    def post(self, request):
        """Envia a 1ª mensagem (cria a conversa) ou só cria uma conversa vazia."""
        ctx, err = self.ctx(request)
        if err:
            return err
        conv = Conversation.objects.create(organization=ctx.org, user=ctx.user)
        text = request.data.get('mensagem')
        if text:
            try:
                engine.ask(ctx, conv, str(text))
            except engine.AssistantError as exc:
                return Response({'detail': str(exc), 'conversa': conv_json(conv, True)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(conv_json(conv, True), status=status.HTTP_201_CREATED)


class ConversationDetailView(_Base):
    def get(self, request, pk):
        ctx, err = self.ctx(request)
        if err:
            return err
        conv = self.conv(ctx, pk)
        if not conv:
            return Response({'detail': 'Conversa não encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(conv_json(conv, True))

    def post(self, request, pk):
        ctx, err = self.ctx(request)
        if err:
            return err
        conv = self.conv(ctx, pk)
        if not conv:
            return Response({'detail': 'Conversa não encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            engine.ask(ctx, conv, str(request.data.get('mensagem') or ''))
        except engine.AssistantError as exc:
            return Response({'detail': str(exc), 'conversa': conv_json(conv, True)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(conv_json(conv, True))

    def delete(self, request, pk):
        ctx, err = self.ctx(request)
        if err:
            return err
        conv = self.conv(ctx, pk)
        if not conv:
            return Response({'detail': 'Conversa não encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        conv.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActionDecideView(_Base):
    def post(self, request, pk):
        ctx, err = self.ctx(request)
        if err:
            return err
        action = PendingAction.objects.filter(pk=pk, conversation__organization=ctx.org, conversation__user=ctx.user) \
            .select_related('conversation').first()
        if not action:
            return Response({'detail': 'Ação não encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        decision = request.data.get('decisao')
        if decision not in ('confirmar', 'cancelar'):
            return Response({'detail': 'Informe decisao: confirmar ou cancelar.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            engine.confirm(ctx, action, decision == 'confirmar')
        except engine.AssistantError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(conv_json(action.conversation, True))


class WriteView(_Base):
    """Corrigir / reescrever / resumir / extrair — usado pelo botão "Escrever com IA" em qualquer campo de texto."""

    def post(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        try:
            out = engine.write(ctx, str(request.data.get('acao') or ''), str(request.data.get('texto') or ''),
                               str(request.data.get('instrucoes') or ''))
        except engine.AssistantError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(out)
