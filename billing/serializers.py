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
    return {
        'plano': SubscriptionPlanSerializer(plan).data,
        'status': 'ativo' if organization.is_active else 'inativo',
        'proxima_cobranca': (
            organization.next_billing_date.isoformat()
            if organization.next_billing_date
            else None
        ),
        'outros_planos': SubscriptionPlanSerializer(outros, many=True).data,
    }
