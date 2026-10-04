"""Regras de crédito: total mensal do plano (escritório) + cota mensal por membro."""
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from billing.entitlements import PAUSED_MESSAGE, ai_enabled, effective_monthly_credits
from billing.models import AIUsageLog, CreditLot, MemberCreditUsage

PLAN_LIMIT_MESSAGE = "Limite de créditos do plano atingido."
MEMBER_LIMIT_MESSAGE = "Limite de créditos individual atingido."


def current_billing_month():
    return timezone.localdate().replace(day=1)


def _membership_for(organization, user_id):
    if not user_id:
        return None
    from accounts.models import OrganizationMembership

    return OrganizationMembership.objects.filter(
        organization=organization,
        user_id=user_id,
        is_active=True,
    ).first()


def organization_credits_used(organization, month=None):
    usage = AIUsageLog.objects.filter(
        organization=organization,
        billing_cycle_month=month or current_billing_month(),
    ).first()
    return usage.extractions_count if usage else 0


def member_credits_used(membership, month=None):
    usage = MemberCreditUsage.objects.filter(
        membership=membership,
        billing_cycle_month=month or current_billing_month(),
    ).first()
    return usage.credits_used if usage else 0


def distributed_credits(organization, *, exclude_membership_id=None):
    from accounts.models import OrganizationMembership

    qs = OrganizationMembership.objects.filter(
        organization=organization,
        is_active=True,
        credit_limit__isnull=False,
    )
    if exclude_membership_id is not None:
        qs = qs.exclude(pk=exclude_membership_id)
    return qs.aggregate(total=Sum("credit_limit"))["total"] or 0


def _purchased_available(organization, now=None):
    return CreditLot.objects.filter(organization=organization, expires_at__gt=now or timezone.now()) \
        .aggregate(total=Sum("credits_remaining"))["total"] or 0


def check_credit_available(organization, user_id=None):
    """Só verifica saldo (plano do estado atual + créditos avulsos + cota do membro), sem descontar."""
    if not ai_enabled(organization):
        return False, PAUSED_MESSAGE
    month = current_billing_month()
    plan_left = effective_monthly_credits(organization) - organization_credits_used(organization, month)
    if plan_left <= 0 and _purchased_available(organization) <= 0:
        return False, PLAN_LIMIT_MESSAGE

    membership = _membership_for(organization, user_id)
    if membership is not None and membership.credit_limit is not None:
        if member_credits_used(membership, month) >= membership.credit_limit:
            return False, MEMBER_LIMIT_MESSAGE
    return True, ""


def _take_from_lots(organization, amount, now):
    """Desconta ``amount`` dos lotes comprados (o que vence primeiro sai primeiro). Chamar dentro de transaction.atomic()."""
    for lot in CreditLot.objects.select_for_update().filter(
            organization=organization, expires_at__gt=now, credits_remaining__gt=0).order_by("expires_at", "id"):
        take = min(lot.credits_remaining, amount)
        lot.credits_remaining -= take
        lot.save(update_fields=["credits_remaining"])
        amount -= take
        if amount == 0:
            return True
    return amount == 0


def consume_credit(organization, user_id=None, amount=1):
    """Verifica e desconta créditos: primeiro os do plano (mês), depois os avulsos; respeita a cota do membro."""
    if not ai_enabled(organization):
        return False, PAUSED_MESSAGE
    month = current_billing_month()
    now = timezone.now()
    with transaction.atomic():
        org_usage, _ = AIUsageLog.objects.select_for_update().get_or_create(
            organization=organization,
            billing_cycle_month=month,
        )
        plan_left = max(effective_monthly_credits(organization, now) - org_usage.extractions_count, 0)
        from_plan = min(plan_left, amount)
        from_lots = amount - from_plan
        if from_lots and _purchased_available(organization, now) < from_lots:
            return False, PLAN_LIMIT_MESSAGE

        membership = _membership_for(organization, user_id)
        member_usage = None
        if membership is not None:
            member_usage, _ = MemberCreditUsage.objects.select_for_update().get_or_create(
                membership=membership,
                billing_cycle_month=month,
            )
            if (
                membership.credit_limit is not None
                and member_usage.credits_used + amount > membership.credit_limit
            ):
                return False, MEMBER_LIMIT_MESSAGE

        if from_lots and not _take_from_lots(organization, from_lots, now):
            return False, PLAN_LIMIT_MESSAGE
        # o contador mensal acompanha só o que saiu do plano; o que saiu de lote não "consome" o mês seguinte
        org_usage.extractions_count += from_plan
        org_usage.save(update_fields=["extractions_count"])
        if member_usage is not None:
            member_usage.credits_used += amount
            member_usage.save(update_fields=["credits_used"])
    return True, ""
