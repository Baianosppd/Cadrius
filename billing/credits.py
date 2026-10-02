"""Regras de crédito: total mensal do plano (escritório) + cota mensal por membro."""
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from billing.models import AIUsageLog, MemberCreditUsage

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


def check_credit_available(organization, user_id=None):
    """Só verifica saldo (plano + cota do membro), sem descontar."""
    month = current_billing_month()
    if organization_credits_used(organization, month) >= organization.plan.max_ai_extractions:
        return False, PLAN_LIMIT_MESSAGE

    membership = _membership_for(organization, user_id)
    if membership is not None and membership.credit_limit is not None:
        if member_credits_used(membership, month) >= membership.credit_limit:
            return False, MEMBER_LIMIT_MESSAGE
    return True, ""


def consume_credit(organization, user_id=None, amount=1):
    """Verifica e desconta créditos do plano e, se houver membro, da cota dele."""
    month = current_billing_month()
    with transaction.atomic():
        org_usage, _ = AIUsageLog.objects.select_for_update().get_or_create(
            organization=organization,
            billing_cycle_month=month,
        )
        if org_usage.extractions_count + amount > organization.plan.max_ai_extractions:
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

        org_usage.extractions_count += amount
        org_usage.save(update_fields=["extractions_count"])
        if member_usage is not None:
            member_usage.credits_used += amount
            member_usage.save(update_fields=["credits_used"])
    return True, ""
