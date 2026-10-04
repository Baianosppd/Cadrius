from rest_framework import serializers

from billing.models import SubscriptionPlan
from billing.plans import format_plan_price, plan_description, plan_features


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = ['id', 'name', 'price', 'description', 'features']

    def get_price(self, obj):
        return format_plan_price(obj)

    def get_description(self, obj):
        return plan_description(obj)

    def get_features(self, obj):
        return plan_features(obj)


def current_plan_payload(organization):
    plan = organization.plan
    outros = (
        SubscriptionPlan.objects.filter(is_active=True)
        .exclude(pk=plan.pk)
        .order_by('price_brl', 'id')
    )
    from billing.entitlements import (ai_enabled, effective_max_users, effective_monthly_credits, effective_status,
                                      purchased_credits_balance)
    return {
        'assinatura': {
            'estado': effective_status(organization),
            'trial_termina_em': organization.trial_ends_at.isoformat() if organization.trial_ends_at else None,
            'periodo_atual_termina_em': organization.current_period_end.isoformat() if organization.current_period_end else None,
            'ia_ativa': ai_enabled(organization),
            'creditos_mensais': effective_monthly_credits(organization),
            'usuarios_maximos': effective_max_users(organization),
            'creditos_avulsos': purchased_credits_balance(organization),
        },
        'plano': SubscriptionPlanSerializer(plan).data,
        'status': 'ativo' if organization.is_active else 'inativo',
        'proxima_cobranca': (
            organization.next_billing_date.isoformat()
            if organization.next_billing_date
            else None
        ),
        'outros_planos': SubscriptionPlanSerializer(outros, many=True).data,
    }
