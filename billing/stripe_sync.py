"""Aplica eventos do Stripe ao estado da assinatura (CAD-119). Funções puras sobre o payload do evento → testáveis sem rede.

Regras de segurança:
* o plano só é promovido com ``payment_status == 'paid'`` **e** valor pago == preço do plano (``amount_total``);
* compra de créditos idempotente: ``CreditLot.stripe_session_id`` é único (webhook reenviado não duplica);
* nada aqui confia em dados vindos do navegador: o ``plan_id``/``pack_id`` são os que NÓS gravamos nos metadados ao criar a sessão.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_tz

from django.conf import settings
from django.utils import timezone

from accounts.models import Organization
from audit import service as audit
from billing.entitlements import ACTIVE, CANCELED, PAST_DUE
from billing.models import CreditLot, CreditPack, SubscriptionPlan

logger = logging.getLogger(__name__)


def _cents(value) -> int:
    return int(round(float(value) * 100))


def _org_by_ref(ref):
    try:
        return Organization.objects.get(pk=ref)
    except (Organization.DoesNotExist, ValueError, TypeError):
        return None


def _org_by_subscription(subscription_id):
    return Organization.objects.filter(stripe_subscription_id=subscription_id).first() if subscription_id else None


def _invoice_subscription_id(invoice):
    # API antiga: invoice.subscription; API nova: invoice.parent.subscription_details.subscription
    return invoice.get('subscription') or (((invoice.get('parent') or {}).get('subscription_details') or {}).get('subscription'))


def _period_end(invoice):
    try:
        ts = invoice['lines']['data'][0]['period']['end']
        return datetime.fromtimestamp(int(ts), tz=dt_tz.utc)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _checkout_completed(session) -> str:
    org = _org_by_ref(session.get('client_reference_id'))
    if org is None:
        logger.warning('Stripe: client_reference_id desconhecido')
        return 'ignored:unknown_org'
    meta = session.get('metadata') or {}
    if session.get('payment_status') != 'paid':
        return 'ignored:not_paid'
    kind = meta.get('kind', 'subscription')

    if kind == 'credit_pack':
        pack = CreditPack.objects.filter(pk=meta.get('pack_id'), is_active=True).first()
        if pack is None or session.get('amount_total') != _cents(pack.price_brl):
            audit.log('billing.payment_confirmed', actor_type='webhook', organization=org, outcome='denied',
                      reason='pacote de créditos: valor pago não confere')
            return 'ignored:pack_mismatch'
        validity = getattr(settings, 'CREDIT_PACK_VALIDITY_DAYS', 365)
        _, created = CreditLot.objects.get_or_create(
            stripe_session_id=session['id'],
            defaults=dict(organization=org, credits_total=pack.credits, credits_remaining=pack.credits,
                          expires_at=timezone.now() + timedelta(days=validity)))
        if created:
            audit.log('billing.credits_purchased', actor_type='webhook', organization=org, changes={'credits': pack.credits})
        return 'credits_added' if created else 'duplicate'

    plan = SubscriptionPlan.objects.filter(pk=meta.get('plan_id'), is_active=True).first()
    if plan is None or session.get('amount_total') != _cents(plan.price_brl):
        audit.log('billing.payment_confirmed', actor_type='webhook', organization=org, outcome='denied',
                  reason='assinatura: plano inválido ou valor pago não confere')
        return 'ignored:plan_mismatch'
    org.plan = plan
    org.subscription_status = ACTIVE
    org.past_due_since = None
    org.is_active = True
    org.stripe_customer_id = session.get('customer') or org.stripe_customer_id
    org.stripe_subscription_id = session.get('subscription') or org.stripe_subscription_id
    org.save()
    audit.log('billing.payment_confirmed', actor_type='webhook', organization=org, reason='checkout.session.completed',
              changes={'plan_id': plan.pk})
    return 'subscription_active'


def _payment_succeeded(invoice) -> str:
    org = _org_by_subscription(_invoice_subscription_id(invoice))
    if org is None:
        return 'ignored:unknown_subscription'
    org.subscription_status = ACTIVE
    org.past_due_since = None
    end = _period_end(invoice)
    if end:
        org.current_period_end = end
        org.next_billing_date = end.date()
    org.save()
    return 'renewed'


def _payment_failed(invoice) -> str:
    org = _org_by_subscription(_invoice_subscription_id(invoice))
    if org is None:
        return 'ignored:unknown_subscription'
    if org.subscription_status != PAST_DUE:
        org.subscription_status = PAST_DUE
        org.past_due_since = timezone.now()
        org.save(update_fields=['subscription_status', 'past_due_since'])
        audit.log('billing.payment_failed', actor_type='webhook', organization=org, outcome='error',
                  reason='falha na cobrança; carência iniciada')
    return 'past_due'


def _subscription_deleted(subscription) -> str:
    org = _org_by_subscription(subscription.get('id'))
    if org is None:
        return 'ignored:unknown_subscription'
    org.subscription_status = CANCELED
    org.save(update_fields=['subscription_status'])
    audit.log('billing.subscription_canceled', actor_type='webhook', organization=org)
    return 'canceled'


HANDLERS = {
    'checkout.session.completed': _checkout_completed,
    'invoice.payment_succeeded': _payment_succeeded,
    'invoice.paid': _payment_succeeded,
    'invoice.payment_failed': _payment_failed,
    'customer.subscription.deleted': _subscription_deleted,
}


def apply_event(event) -> str:
    handler = HANDLERS.get(event['type'])
    return handler(event['data']['object']) if handler else 'ignored:event_type'
