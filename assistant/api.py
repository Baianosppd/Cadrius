"""API do assistente (CAD-221). Prefixo /api/v1/assistant/. Cada pessoa só vê as próprias conversas."""
from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from aigov import llm
from assistant import engine
from assistant.models import AssistantSettings, Conversation, PendingAction
from assistant.tools import TOOLS


def action_json(a: PendingAction) -> dict:
    tool = TOOLS.get(a.tool)
    return {'id': a.pk, 'ferramenta': a.tool, 'rotulo': tool.label if tool else a.tool, 'resumo': a.summary, 'argumentos': a.arguments,
            'status': a.status, 'resultado': a.result, 'criada_em': a.created_at, 'decidida_em': a.decided_at,
            'mensagem_id': a.message_id}


def conv_json(c: Conversation, full=False) -> dict:
    data = {'id': c.pk, 'titulo': c.title or 'Nova conversa', 'atualizada_em': c.updated_at, 'modo': c.mode,
            'processo': c.case.cnj if c.case_id else '', 'processo_id': c.case_id}
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
        cfg = AssistantSettings.of(ctx.org)
        return Response({'disponivel': bool(seguros) and policy.ai_enabled and global_ai_enabled(), 'provedores': seguros,
                         'estrategia_de_caso': cfg.case_strategy, 'conector_mcp': cfg.mcp_enabled, 'usa_memoria': cfg.use_memory,
                         'pode_configurar': ctx.role in engine.MANAGER_ROLES,
                         'ia_ligada': policy.ai_enabled and global_ai_enabled(), 'pode_agir': ctx.role in engine.WRITE_ROLES,
                         'escrita': sorted(engine.WRITING), 'ferramentas': [{'nome': t.name, 'rotulo': t.label, 'acao': t.action}
                                                                            for t in TOOLS.values()]})


class ConversationListView(_Base):
    def get(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        rows = Conversation.objects.filter(organization=ctx.org, user=ctx.user).select_related('case')[:50]
        return Response([conv_json(c) for c in rows])

    def post(self, request):
        """Envia a 1ª mensagem (cria a conversa) ou só cria uma conversa vazia."""
        ctx, err = self.ctx(request)
        if err:
            return err
        mode = request.data.get('modo') or 'geral'
        fields = {}
        if mode == 'caso':
            if not AssistantSettings.of(ctx.org).case_strategy:
                return Response({'detail': 'O modo estratégia de caso está desligado. Dono/admin liga em Assistente → Configurações.'},
                                status=status.HTTP_403_FORBIDDEN)
            from research.models import MonitoredCase
            pid = request.data.get('processo_id')
            if pid:
                case = MonitoredCase.objects.filter(organization=ctx.org, pk=pid).first()
                if case is None:
                    return Response({'detail': 'Processo não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
                fields.update(case=case, contact=case.client, title=f'Estratégia: {case.label or case.cnj}'[:120])
            else:
                fields['title'] = 'Estratégia de caso'
        elif mode != 'geral':
            return Response({'detail': 'Modo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        conv = Conversation.objects.create(organization=ctx.org, user=ctx.user, mode=mode, **fields)
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


class SettingsView(_Base):
    """GET/PATCH configurações do assistente do escritório (alterar: dono/admin)."""

    def get(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        cfg = AssistantSettings.of(ctx.org)
        return Response({'estrategia_de_caso': cfg.case_strategy, 'conector_mcp': cfg.mcp_enabled, 'usa_memoria': cfg.use_memory})

    def patch(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        if ctx.role not in engine.MANAGER_ROLES:
            return Response({'detail': 'Só dono ou administrador altera.'}, status=status.HTTP_403_FORBIDDEN)
        cfg = AssistantSettings.of(ctx.org)
        for key, field in (('estrategia_de_caso', 'case_strategy'), ('conector_mcp', 'mcp_enabled'), ('usa_memoria', 'use_memory')):
            if key in request.data:
                setattr(cfg, field, bool(request.data[key]))
        cfg.save()
        from audit import service as audit
        audit.log('org.updated', actor=request.user, organization=ctx.org,
                  changes={'assistente': {'estrategia_de_caso': cfg.case_strategy, 'conector_mcp': cfg.mcp_enabled,
                                          'usa_memoria': cfg.use_memory}})
        if not cfg.mcp_enabled:
            from assistant.models import PersonalToken
            PersonalToken.objects.filter(organization=ctx.org, revoked_at__isnull=True).update(revoked_at=timezone.now())
        return self.get(request)
