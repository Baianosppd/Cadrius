"""Guarda de governança: toda chamada de IA passa por aqui (permitir → executar → registrar)."""
from __future__ import annotations

import time
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from audit import service as audit
from audit.context import get_context
from aigov.models import AIActionLog, AIGovernancePolicy, GlobalAISwitch


class AIBlocked(Exception):
    """A chamada de IA foi bloqueada por política. ``code`` identifica o motivo."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def get_policy(organization) -> AIGovernancePolicy:
    policy, _ = AIGovernancePolicy.objects.get_or_create(organization=organization)
    return policy


def global_ai_enabled() -> bool:
    cached = cache.get('aigov:global')
    if cached is None:
        cached = GlobalAISwitch.get().ai_enabled
        cache.set('aigov:global', cached, 15)
    return cached


def set_global_switch(enabled: bool, *, reason='', changed_by='') -> GlobalAISwitch:
    switch = GlobalAISwitch.get()
    switch.ai_enabled, switch.reason, switch.changed_by, switch.changed_at = enabled, reason[:255], changed_by, timezone.now()
    switch.save()
    cache.delete('aigov:global')
    audit.log('ai.blocked' if not enabled else 'ai.request', actor_type='system',
              reason=f'kill switch global {"DESLIGADO" if not enabled else "religado"}: {reason}'[:255],
              changes={'global_ai_enabled': enabled, 'by': changed_by})
    return switch


def check(organization, kind: str, provider: str) -> AIGovernancePolicy:
    """Levanta ``AIBlocked`` se a política não permitir esta chamada; devolve a política se permitir."""
    if not global_ai_enabled():
        raise AIBlocked('global_kill_switch', 'IA temporariamente desativada pela plataforma.')
    policy = get_policy(organization)
    if not policy.ai_enabled or policy.autonomy_level == AIGovernancePolicy.Autonomy.OFF:
        raise AIBlocked('org_disabled', 'A IA está desativada para este escritório.')
    if provider not in policy.allowed_providers:
        raise AIBlocked('provider_not_allowed', f'O provedor {provider} não está autorizado pelo escritório.')
    if kind == AIActionLog.Kind.EXTRACTION and policy.autonomy_level == AIGovernancePolicy.Autonomy.SUGGEST:
        raise AIBlocked('suggest_only', 'No modo "somente sugestões" a extração automática está desligada.')
    since = timezone.now() - timedelta(days=1)
    used = AIActionLog.objects.filter(organization_id=organization.pk, created_at__gte=since, blocked=False).count()
    if used >= policy.daily_ai_request_limit:
        raise AIBlocked('daily_limit', 'Limite diário de pedidos de IA do escritório atingido.')
    return policy


def run_guarded(*, organization, user=None, kind: str, provider: str, categories=(), input_text: str = '', fn):
    """
    Executa ``fn()`` (a chamada real à IA) sob governança. Bloqueios e execuções ficam em
    ``AIActionLog`` + trilha de auditoria (sem conteúdo). Propaga ``AIBlocked`` ao chamador.
    """
    ctx = get_context()
    base = dict(
        organization_id=organization.pk, user_ref=str(getattr(user, 'pk', '') or ''), kind=kind,
        provider=provider, data_categories=list(categories), input_chars=len(input_text or ''),
        request_id=ctx.request_id,
    )
    try:
        check(organization, kind, provider)
    except AIBlocked as blocked:
        AIActionLog.objects.create(**base, blocked=True, success=False, block_reason=blocked.code)
        audit.log('ai.blocked', actor=user, organization=organization, outcome='denied', reason=blocked.code,
                  changes={'kind': kind, 'provider': provider})
        raise

    started = time.monotonic()
    ok = False
    try:
        result = fn()
        ok = result is not None
        return result
    finally:
        AIActionLog.objects.create(**base, success=ok, duration_ms=int((time.monotonic() - started) * 1000))
        audit.log('ai.request', actor=user, organization=organization, outcome='success' if ok else 'error',
                  changes={'kind': kind, 'provider': provider, 'input_chars': base['input_chars']},
                  data_categories=list(categories), legal_basis='contrato')
