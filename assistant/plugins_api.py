"""Plugins (CAD-222): conector MCP (Claude/ChatGPT) e chave de IA do próprio escritório. Prefixo /api/v1/assistant/plugins/."""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from aigov import llm
from assistant import engine, mcp
from assistant.api import _Base
from assistant.models import AssistantSettings, OrgAIKey, PersonalToken
from audit import service as audit

BYOK = ('ANTHROPIC', 'OPENAI', 'GEMINI', 'MARITACA', 'MISTRAL', 'GROQ', 'OPENROUTER', 'OLLAMA')


def mcp_base(request) -> str:
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/') or request.build_absolute_uri('/').rstrip('/')
    return f'{base}/mcp/'


def token_json(t: PersonalToken) -> dict:
    return {'id': t.pk, 'nome': t.name, 'prefixo': t.prefix, 'escopo': t.scope, 'criado_em': t.created_at, 'expira_em': t.expires_at,
            'ultimo_uso': t.last_used_at, 'usos': t.uses, 'ativo': t.revoked_at is None and t.expires_at > timezone.now()}


def key_json(k: OrgAIKey) -> dict:
    p = llm.PROVIDERS[k.provider]
    return {'provedor': k.provider, 'nome': p.label, 'final': k.last4, 'modelo': k.model or llm.model_for(p), 'conta_paga': k.paid_account,
            'endereco': k.base_url, 'criada_em': k.created_at, 'ultimo_uso': k.last_used_at}


class PluginsView(_Base):
    def get(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        cfg = AssistantSettings.of(ctx.org)
        tokens = PersonalToken.objects.filter(organization=ctx.org, user=ctx.user)
        return Response({
            'conector': {'ligado': cfg.mcp_enabled, 'url': mcp_base(request), 'tokens': [token_json(t) for t in tokens[:20]]},
            'chaves': [key_json(k) for k in OrgAIKey.objects.filter(organization=ctx.org)],
            'provedores': [{'chave': k, 'nome': llm.PROVIDERS[k].label, 'site': llm.PROVIDERS[k].site,
                            'treina_no_gratis': llm.PROVIDERS[k].trains_on_free} for k in BYOK],
            'pode_configurar': ctx.role in engine.MANAGER_ROLES,
        })


class TokenCreateView(_Base):
    def post(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        if not AssistantSettings.of(ctx.org).mcp_enabled:
            return Response({'detail': 'O conector está desligado. Dono/admin liga em Plugins.'}, status=status.HTTP_403_FORBIDDEN)
        name = str(request.data.get('nome') or 'Claude').strip()[:80]
        scope = request.data.get('escopo') or 'leitura'
        if scope not in PersonalToken.Scope.values:
            return Response({'detail': 'Escopo: leitura ou pedidos.'}, status=status.HTTP_400_BAD_REQUEST)
        if scope == 'pedidos' and ctx.role not in engine.WRITE_ROLES:
            return Response({'detail': 'Seu perfil é só de leitura.'}, status=status.HTTP_403_FORBIDDEN)
        if PersonalToken.objects.filter(user=ctx.user, revoked_at__isnull=True, expires_at__gt=timezone.now()).count() >= 5:
            return Response({'detail': 'Máximo de 5 tokens ativos. Revogue um antes.'}, status=status.HTTP_400_BAD_REQUEST)
        raw, prefix, digest = mcp.new_token()
        tok = PersonalToken.objects.create(organization=ctx.org, user=ctx.user, name=name, prefix=prefix, token_hash=digest, scope=scope,
                                           expires_at=mcp.default_expiry())
        audit.log('assistant.token_created', actor=ctx.user, organization=ctx.org, target=tok, changes={'escopo': scope, 'prefixo': prefix},
                  data_categories=['credenciais'])
        base = mcp_base(request)
        response = Response({**token_json(tok), 'token': raw, 'url_com_token': f'{base}{raw}/', 'url': base},
                            status=status.HTTP_201_CREATED)
        response['Cache-Control'] = 'no-store'                  # o token aparece uma única vez
        return response


class TokenRevokeView(_Base):
    def delete(self, request, pk):
        ctx, err = self.ctx(request)
        if err:
            return err
        qs = PersonalToken.objects.filter(organization=ctx.org, pk=pk)
        if ctx.role not in engine.MANAGER_ROLES:
            qs = qs.filter(user=ctx.user)
        tok = qs.first()
        if tok is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        tok.revoked_at = tok.revoked_at or timezone.now()
        tok.save(update_fields=['revoked_at'])
        audit.log('assistant.token_revoked', actor=ctx.user, organization=ctx.org, target=tok, changes={'prefixo': tok.prefix})
        return Response(status=status.HTTP_204_NO_CONTENT)


class KeyView(_Base):
    """POST {provedor, chave, modelo?, endereco? (Ollama), conta_paga} · DELETE ?provedor= — só dono/admin."""

    def post(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        if ctx.role not in engine.MANAGER_ROLES:
            return Response({'detail': 'Só dono ou administrador cadastra a conta de IA do escritório.'}, status=status.HTTP_403_FORBIDDEN)
        provider = str(request.data.get('provedor') or '').upper()
        if provider not in BYOK:
            return Response({'detail': 'Provedor inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        key = str(request.data.get('chave') or '').strip()
        base_url = str(request.data.get('endereco') or '').strip()
        if provider == 'OLLAMA':
            from integrations.ssrf import UnsafeURLError, validate_outbound_url
            if not base_url.startswith('https://'):
                return Response({'detail': 'Informe o endereço HTTPS do seu servidor de modelos.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                validate_outbound_url(base_url)
            except UnsafeURLError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            key = key or 'ollama'
        elif len(key) < 16:
            return Response({'detail': 'Cole a chave de API completa.'}, status=status.HTTP_400_BAD_REQUEST)
        obj, created = OrgAIKey.objects.update_or_create(
            organization=ctx.org, provider=provider,
            defaults={'api_key': key, 'base_url': base_url[:255], 'model': str(request.data.get('modelo') or '')[:80],
                      'paid_account': bool(request.data.get('conta_paga', True)), 'last4': key[-4:], 'created_by': ctx.user})
        audit.log('assistant.key_saved', actor=ctx.user, organization=ctx.org, target=obj, changes={'provedor': provider, 'novo': created},
                  data_categories=['credenciais'])
        return Response(key_json(obj), status=status.HTTP_201_CREATED)

    def delete(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        if ctx.role not in engine.MANAGER_ROLES:
            return Response(status=status.HTTP_403_FORBIDDEN)
        provider = str(request.query_params.get('provedor') or '').upper()
        deleted, _ = OrgAIKey.objects.filter(organization=ctx.org, provider=provider).delete()
        if deleted:
            audit.log('assistant.key_removed', actor=ctx.user, organization=ctx.org, changes={'provedor': provider})
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


class KeyTestView(_Base):
    def post(self, request):
        ctx, err = self.ctx(request)
        if err:
            return err
        if ctx.role not in engine.MANAGER_ROLES:
            return Response(status=status.HTTP_403_FORBIDDEN)
        provider = str(request.data.get('provedor') or '').upper()
        if not OrgAIKey.objects.filter(organization=ctx.org, provider=provider).exists():
            return Response({'detail': 'Cadastre a chave primeiro.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            reply = llm.call(provider, system='Responda apenas: OK', messages=[{'role': 'user', 'content': 'teste'}], max_tokens=20,
                             org=ctx.org)
        except Exception:  # noqa: BLE001 — mensagem segura, sem detalhe do provedor
            return Response({'ok': False, 'detail': 'A chave não funcionou (confira chave, modelo e créditos na conta do provedor).'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({'ok': True, 'modelo': reply.model})
