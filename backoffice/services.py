"""Leituras e ações da Gestão Cadrius (CAD-168). Toda AÇÃO exige motivo e vai para a trilha de auditoria (``backoffice.action``)."""
from __future__ import annotations

import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from audit import service as audit
from billing import entitlements as ent
from billing.credits import organization_credits_used
from core.pii import mask_text


class ActionError(Exception):
    pass


# ----------------------------------------------------------------------------- saúde
def _timed(fn):
    start = time.monotonic()
    try:
        fn()
        return 'ok', round((time.monotonic() - start) * 1000, 1)
    except Exception:  # noqa: BLE001 — painel de saúde: qualquer falha vira "error", sem derrubar a tela
        return 'error', None


def _db():
    with connection.cursor() as cur:
        cur.execute('SELECT 1')


def _cache():
    cache.set('backoffice:ping', '1', timeout=5)
    if cache.get('backoffice:ping') != '1':
        raise RuntimeError('cache')


def queue_info() -> dict:
    from django_q.models import Failure, Schedule, Success

    since = timezone.now() - timedelta(hours=24)
    info = {'falhas_24h': Failure.objects.filter(stopped__gte=since).count(),
            'sucessos_24h': Success.objects.filter(stopped__gte=since).count(),
            'fila': None, 'workers': None}
    try:
        from django_q.brokers import get_broker
        info['fila'] = get_broker().queue_size()
    except Exception:  # noqa: BLE001
        pass
    try:
        from django_q.status import Stat
        info['workers'] = sum(len(s.workers) for s in Stat.get_all())
    except Exception:  # noqa: BLE001
        pass
    info['ultimas_falhas'] = [
        {'id': f.id, 'nome': f.name, 'funcao': f.func, 'quando': f.stopped,
         'erro': mask_text(str(f.result or ''))[:300]}                       # resultado pode conter dado pessoal: mascarado
        for f in Failure.objects.order_by('-stopped')[:20]]
    info['rotinas'] = [{'nome': s.name, 'comando': s.args or s.func, 'proxima': s.next_run, 'repete': s.repeats}
                       for s in Schedule.objects.order_by('name')]
    return info


def config_flags() -> dict:
    """O que está configurado (sim/não) — nunca o valor do segredo."""
    def has(name):
        return bool(getattr(settings, name, '') or '')
    return {
        'versao': getattr(settings, 'APP_VERSION', ''),
        'debug': settings.DEBUG,
        'email': has('EMAIL_HOST'),
        'email_provedor': getattr(settings, 'EMAIL_PROVIDER', ''),
        'stripe': has('STRIPE_SECRET_KEY'),
        'stripe_webhook': has('STRIPE_WEBHOOK_SECRET'),
        'sentry': has('SENTRY_DSN'),
        'sso_google': has('GOOGLE_CLIENT_ID'),
        'sso_microsoft': has('MICROSOFT_CLIENT_ID'),
        'datajud': has('DATAJUD_API_KEY'),
        'noticias_fontes': len(getattr(settings, 'NEWS_FEEDS', []) or []),
        'openai': has('OPENAI_API_KEY'), 'groq': has('GROQ_API_KEY'), 'gemini': has('GEMINI_API_KEY'),
    }


def health() -> dict:
    from aigov.models import GlobalAISwitch
    from compliance import checks

    db, db_ms = _timed(_db)
    ca, ca_ms = _timed(_cache)
    results = checks.run_all()
    switch = GlobalAISwitch.get()
    return {
        'servicos': {'banco': {'status': db, 'ms': db_ms}, 'cache_redis': {'status': ca, 'ms': ca_ms}},
        'fila': queue_info(),
        'config': config_flags(),
        'ia_global': {'ligada': switch.ai_enabled, 'motivo': switch.reason, 'alterado_em': switch.changed_at},
        'verificacoes': [{'nome': n, 'titulo': checks.TITLES.get(n, n), 'status': r.status, 'detalhe': r.detail}
                         for n, r in results.items()],
    }


# ----------------------------------------------------------------------------- escritórios
def org_row(org, now=None) -> dict:
    now = now or timezone.now()
    return {
        'id': str(org.pk), 'nome': str(org), 'tipo': org.account_type, 'plano': org.plan.name if org.plan_id else '',
        'estado': ent.effective_status(org, now), 'estado_registrado': org.subscription_status,
        'ativo': org.is_active, 'membros': getattr(org, 'n_members', None),
        'trial_ate': org.trial_ends_at, 'pendente_desde': org.past_due_since, 'periodo_ate': org.current_period_end,
        'stripe': bool(org.stripe_subscription_id), 'criado_em': org.created_at,
    }


def org_detail(org) -> dict:
    from billing.models import CreditLot

    now = timezone.now()
    data = org_row(org, now)
    members = org.members.select_related('user').order_by('-is_active', 'role')
    data.update({
        'membros': sum(1 for m in members if m.is_active),
        'creditos': {'mes_usados': organization_credits_used(org), 'mes_limite': ent.effective_monthly_credits(org, now),
                     'avulsos_disponiveis': ent.purchased_credits_balance(org, now)},
        'limite_usuarios': ent.effective_max_users(org, now),
        'equipe': [{'id': str(m.user_id), 'email': m.user.email, 'nome': m.user.get_full_name(), 'papel': m.role,
                    'ativo': m.is_active and m.user.is_active, 'ultimo_acesso': m.user.last_login} for m in members],
        'lotes': [{'creditos': lot.credits_total, 'restantes': lot.credits_remaining, 'expira': lot.expires_at,
                   'origem': 'cortesia' if lot.stripe_session_id.startswith('manual:') else 'compra',
                   'valor_brl': round(lot.amount_paid_cents / 100, 2)}
                  for lot in CreditLot.objects.filter(organization=org).order_by('-created_at')[:20]],
    })
    return data


def revoke_sessions(user) -> int:
    n = 0
    for outstanding in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
        n += int(created)
    return n


def _log(actor, action, *, organization=None, target=None, reason='', params=None):
    audit.log('backoffice.action', actor=actor, organization=organization, target=target, reason=reason[:255],
              changes={'action': action, **(params or {})})


def org_action(actor, org, action: str, params: dict, reason: str) -> dict:
    from billing.models import CreditLot

    now = timezone.now()
    if action == 'extend_trial':
        days = int(params.get('days') or 0)
        if not 1 <= days <= 60:
            raise ActionError('Dias de extensão: entre 1 e 60.')
        if org.subscription_status != ent.TRIALING:
            raise ActionError('Só dá para estender o teste de um escritório em teste.')
        base = max(org.trial_ends_at or now, now)
        org.trial_ends_at = base + timedelta(days=days)
        org.save(update_fields=['trial_ends_at'])
        result = {'trial_ate': org.trial_ends_at}
        params = {'days': days}
    elif action == 'grant_credits':
        credits, valid = int(params.get('credits') or 0), int(params.get('valid_days') or 90)
        if not 1 <= credits <= 10000 or not 1 <= valid <= 365:
            raise ActionError('Créditos: 1 a 10.000; validade: 1 a 365 dias.')
        CreditLot.objects.create(organization=org, credits_total=credits, credits_remaining=credits,
                                 expires_at=now + timedelta(days=valid), stripe_session_id=f'manual:{uuid.uuid4().hex}',
                                 amount_paid_cents=0)
        result = {'avulsos_disponiveis': ent.purchased_credits_balance(org, now)}
        params = {'credits': credits, 'valid_days': valid}
    elif action in ('deactivate', 'activate'):
        org.is_active = action == 'activate'
        org.save(update_fields=['is_active'])
        revoked = 0
        if not org.is_active:
            for m in org.members.filter(is_active=True).select_related('user'):
                revoked += revoke_sessions(m.user)
        result = {'ativo': org.is_active, 'sessoes_encerradas': revoked}
        params = {}
    else:
        raise ActionError('Ação desconhecida.')
    _log(actor, action, organization=org, target=org, reason=reason, params=params)
    return result


# ----------------------------------------------------------------------------- usuários
def is_locked(user) -> bool:
    from axes.models import AccessAttempt
    return AccessAttempt.objects.filter(username=user.get_username(),
                                        failures_since_start__gte=getattr(settings, 'AXES_FAILURE_LIMIT', 5)).exists()


def user_row(user) -> dict:
    return {
        'id': str(user.pk), 'email': user.email, 'nome': user.get_full_name(), 'ativo': user.is_active,
        'equipe_cadrius': user.is_staff, 'superusuario': user.is_superuser,
        'ultimo_acesso': user.last_login, 'criado_em': user.date_joined, 'bloqueado': is_locked(user),
        'escritorios': [{'nome': str(m.organization), 'papel': m.role, 'ativo': m.is_active}
                        for m in user.memberships.select_related('organization')],
    }


def user_action(actor, user, action: str, reason: str) -> dict:
    if action in ('deactivate', 'revoke_sessions') and user.pk == actor.pk:
        raise ActionError('Você não pode aplicar esta ação na própria conta.')
    if user.is_superuser and not actor.is_superuser:
        raise ActionError('Só um superusuário altera outro superusuário.')
    if action == 'unlock':
        from axes.utils import reset
        reset(username=user.get_username())
        result = {'bloqueado': False}
    elif action == 'deactivate':
        user.is_active = False
        user.save(update_fields=['is_active'])
        result = {'ativo': False, 'sessoes_encerradas': revoke_sessions(user)}
    elif action == 'activate':
        user.is_active = True
        user.save(update_fields=['is_active'])
        result = {'ativo': True}
    elif action == 'revoke_sessions':
        result = {'sessoes_encerradas': revoke_sessions(user)}
    elif action == 'send_password_reset':
        if not user.is_active:
            raise ActionError('Conta desativada: ative antes de enviar o link.')
        from accounts.password_reset import send_reset_email
        send_reset_email(user)
        result = {'enviado': True}
    else:
        raise ActionError('Ação desconhecida.')
    _log(actor, action, target=user, reason=reason)
    return result
