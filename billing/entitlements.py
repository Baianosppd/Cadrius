"""O que o escritório PODE usar agora (CAD-119): depende do estado da assinatura, não só do plano escolhido.

* ``trialing``  → limites do trial (``TRIAL_CREDITS`` / ``TRIAL_MAX_USERS``), mesmo que o plano escolhido seja pago;
* ``active``    → limites do plano; ``past_due`` → idem durante a carência (``GRACE_DAYS``);
* depois da carência / trial vencido / cancelado → IA pausada (``restricted``/``suspended``/``canceled``), leitura e exportação liberadas.

O estado "efetivo" é calculado na hora a partir das datas (sem cron): ``trial_ends_at`` e ``past_due_since``.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

TRIALING, ACTIVE, PAST_DUE = 'trialing', 'active', 'past_due'
RESTRICTED, SUSPENDED, CANCELED = 'restricted', 'suspended', 'canceled'
FULL_ACCESS = {ACTIVE, PAST_DUE}
AI_ENABLED = {TRIALING, ACTIVE, PAST_DUE}

PAUSED_MESSAGE = 'Assinatura pendente: IA e automações pausadas. Regularize o pagamento para continuar (seus dados continuam acessíveis).'


def _cfg(name, default):
    return getattr(settings, name, default)


def trial_days() -> int:
    return _cfg('TRIAL_DAYS', 14)


def effective_status(organization, now=None) -> str:
    now = now or timezone.now()
    st = organization.subscription_status
    if st == TRIALING:
        return TRIALING if organization.trial_ends_at and now < organization.trial_ends_at else RESTRICTED
    if st == PAST_DUE and organization.past_due_since:
        days = (now - organization.past_due_since).days
        if days <= _cfg('GRACE_DAYS', 7):
            return PAST_DUE
        if days <= _cfg('RESTRICTED_DAYS', 14):
            return RESTRICTED
        if days <= _cfg('SUSPENDED_DAYS', 30):
            return SUSPENDED
        return CANCELED
    return st


def ai_enabled(organization, now=None) -> bool:
    return effective_status(organization, now) in AI_ENABLED


def effective_monthly_credits(organization, now=None) -> int:
    st = effective_status(organization, now)
    if st in FULL_ACCESS:
        return organization.plan.max_ai_extractions
    if st == TRIALING:
        return min(organization.plan.max_ai_extractions, _cfg('TRIAL_CREDITS', 30))
    return 0


def effective_max_users(organization, now=None) -> int:
    st = effective_status(organization, now)
    if st in FULL_ACCESS:
        return organization.plan.max_users
    if st == TRIALING:
        return min(organization.plan.max_users, _cfg('TRIAL_MAX_USERS', 3))
    return 0  # restrito/suspenso/cancelado: nenhum convite novo


def purchased_credits_balance(organization, now=None) -> int:
    from billing.models import CreditLot
    return CreditLot.objects.filter(organization=organization, expires_at__gt=now or timezone.now()) \
        .aggregate(total=Sum('credits_remaining'))['total'] or 0


def start_trial(organization, now=None) -> None:
    """Chamado no cadastro: o plano escolhido (pago ou não) só vale integralmente depois do pagamento."""
    organization.subscription_status = TRIALING
    organization.trial_ends_at = (now or timezone.now()) + timedelta(days=trial_days())
