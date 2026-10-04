"""API do financeiro da equipe Cadrius (CAD-160): planos/preços, pacotes, promoções, informes, pesos de crédito e resumo.

Só a área Financeiro da Gestão Cadrius (CAD-168). Toda alteração é auditada (``billing.admin_changed``); mudança de preço de plano também vai ao histórico
(``PlanPriceHistory``). **Reajuste não é retroativo**: assinaturas existentes no Stripe mantêm o preço contratado; o novo preço vale
para novas assinaturas.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework import permissions, serializers, viewsets
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from accounts.models import Organization
from audit import service as audit
from billing import entitlements as ent
from billing.credit_weights import ensure_default_weights
from billing.models import (BillingNotice, CreditLot, CreditPack, CreditWeight, PlanPriceHistory, Promotion,
                            SubscriptionPlan)


class IsStaff(permissions.BasePermission):
    """Área Financeiro da Gestão Cadrius (CAD-168): equipe + (superusuário ou grupo "Cadrius Financeiro")."""

    def has_permission(self, request, view):
        from backoffice.permissions import user_areas
        return 'financeiro' in user_areas(request.user)


# ----------------------------------------------------------------------------- serializers
class PlanAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ['id', 'name', 'tier', 'price_brl', 'max_users', 'max_ai_extractions', 'is_active']

    def validate_price_brl(self, value):
        if value < 0:
            raise serializers.ValidationError('Preço não pode ser negativo.')
        return value


class PackAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditPack
        fields = ['id', 'name', 'credits', 'price_brl', 'is_active']

    def validate(self, data):
        if data.get('credits', 1) <= 0 or data.get('price_brl', 1) <= 0:
            raise serializers.ValidationError('Créditos e preço devem ser maiores que zero.')
        return data


class PromotionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promotion
        fields = ['id', 'code', 'name', 'description', 'kind', 'value', 'duration', 'duration_months', 'plan_tiers',
                  'starts_at', 'ends_at', 'max_redemptions', 'redemptions_count', 'is_active']
        read_only_fields = ['redemptions_count']

    def validate_code(self, value):
        value = value.strip().upper()
        if not value.replace('-', '').replace('_', '').isalnum():
            raise serializers.ValidationError('Use apenas letras, números, hífen e sublinhado.')
        return value

    def validate_plan_tiers(self, value):
        valid = {t for t, _ in SubscriptionPlan.TIER_CHOICES}
        if not isinstance(value, list) or any(t not in valid for t in value):
            raise serializers.ValidationError(f'Planos válidos: {sorted(valid)}.')
        return value

    def validate(self, data):
        inst = self.instance
        kind = data.get('kind', getattr(inst, 'kind', None))
        value = data.get('value', getattr(inst, 'value', None))
        duration = data.get('duration', getattr(inst, 'duration', None))
        months = data.get('duration_months', getattr(inst, 'duration_months', None))
        if kind == Promotion.Kind.PERCENT and not (0 < value < 100):
            raise serializers.ValidationError({'value': 'Percentual deve ficar entre 0 e 100 (exclusive).'})
        if kind == Promotion.Kind.AMOUNT and value <= 0:
            raise serializers.ValidationError({'value': 'O valor do desconto deve ser maior que zero.'})
        if duration == Promotion.Duration.REPEATING and not months:
            raise serializers.ValidationError({'duration_months': 'Informe por quantos meses o desconto vale.'})
        start, end = data.get('starts_at', getattr(inst, 'starts_at', None)), data.get('ends_at', getattr(inst, 'ends_at', None))
        if start and end and end <= start:
            raise serializers.ValidationError({'ends_at': 'O fim deve ser depois do início.'})
        # Depois de usado, o desconto em si não pode mudar (o Stripe já tem o Coupon): crie outro cupom.
        if inst is not None and inst.redemptions_count and any(
                k in data and data[k] != getattr(inst, k) for k in ('kind', 'value', 'duration', 'duration_months')):
            raise serializers.ValidationError('Cupom já usado: crie outro em vez de alterar o desconto.')
        return data


class NoticeAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingNotice
        fields = ['id', 'title', 'body', 'severity', 'audience_tiers', 'audience_statuses', 'starts_at', 'ends_at',
                  'is_active', 'created_at']
        read_only_fields = ['created_at']


class WeightAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditWeight
        fields = ['id', 'operation', 'label', 'credits', 'is_active']
        read_only_fields = ['operation']


# ----------------------------------------------------------------------------- viewsets
class AuditedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStaff]
    pagination_class = None
    label = ''

    def _audit(self, verb, instance, changed=()):
        audit.log('billing.admin_changed', actor=self.request.user, target=instance,
                  changes={'resource': self.label, 'action': verb, 'fields': sorted(changed)})

    def perform_create(self, serializer):
        instance = serializer.save()
        self._audit('created', instance, serializer.validated_data.keys())

    def perform_update(self, serializer):
        instance = serializer.save()
        self._audit('updated', instance, serializer.validated_data.keys())

    def perform_destroy(self, instance):
        self._audit('deleted', instance)
        instance.delete()


class PlanViewSet(AuditedViewSet):
    queryset = SubscriptionPlan.objects.order_by('price_brl', 'id')
    serializer_class = PlanAdminSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']   # plano não se apaga (escritórios referenciam): desative
    label = 'plan'

    def perform_update(self, serializer):
        serializer.instance._changed_by = str(self.request.user.pk)   # o sinal grava "quem" no histórico de preços
        super().perform_update(serializer)


class PackViewSet(AuditedViewSet):
    queryset = CreditPack.objects.order_by('price_brl')
    serializer_class = PackAdminSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    label = 'credit_pack'


class PromotionViewSet(AuditedViewSet):
    queryset = Promotion.objects.order_by('-created_at')
    serializer_class = PromotionAdminSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']   # desative em vez de apagar (há histórico de uso)
    label = 'promotion'


class NoticeViewSet(AuditedViewSet):
    queryset = BillingNotice.objects.order_by('-created_at')
    serializer_class = NoticeAdminSerializer
    label = 'notice'

    def perform_create(self, serializer):
        instance = serializer.save(created_by=str(self.request.user.pk))
        self._audit('created', instance, serializer.validated_data.keys())


class WeightViewSet(AuditedViewSet):
    serializer_class = WeightAdminSerializer
    http_method_names = ['get', 'patch', 'head', 'options']
    label = 'credit_weight'

    def get_queryset(self):
        ensure_default_weights()
        return CreditWeight.objects.order_by('operation')


class PriceHistoryView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        rows = PlanPriceHistory.objects.select_related('plan')[:100]
        return Response([{'plan': r.plan.name, 'tier': r.plan.tier, 'old_price': str(r.old_price), 'new_price': str(r.new_price),
                          'old_credits': r.old_credits, 'new_credits': r.new_credits, 'changed_by': r.changed_by,
                          'changed_at': r.changed_at} for r in rows])


def finance_summary() -> dict:
    """Números do financeiro (também usados na Visão geral da Gestão Cadrius)."""
    now = timezone.now()
    by_status = {s: 0 for s in ('trialing', 'active', 'past_due', 'restricted', 'suspended', 'canceled')}
    mrr, paying, trials_ending = 0, 0, 0
    by_plan = {}
    for org in Organization.objects.select_related('plan'):
        st = ent.effective_status(org, now)
        by_status[st] = by_status.get(st, 0) + 1
        if st == ent.ACTIVE and org.stripe_subscription_id:
            paying += 1
            mrr += org.plan.price_brl
            by_plan[org.plan.name] = by_plan.get(org.plan.name, 0) + 1
        if st == ent.TRIALING and org.trial_ends_at and org.trial_ends_at <= now + timedelta(days=7):
            trials_ending += 1
    packs_30d = CreditLot.objects.filter(created_at__gte=now - timedelta(days=30)).aggregate(
        total=Sum('amount_paid_cents'), credits=Sum('credits_total'))
    return {
        'organizacoes_por_estado': by_status,
        'assinantes_pagantes': paying,
        'mrr_tabela_brl': str(mrr),
        'ticket_medio_brl': str(round(mrr / paying, 2)) if paying else '0',
        'assinantes_por_plano': by_plan,
        'trials_terminando_em_7_dias': trials_ending,
        'pacotes_30d': {'receita_brl': str(round((packs_30d['total'] or 0) / 100, 2)),
                        'creditos_vendidos': packs_30d['credits'] or 0},
        'promocoes_ativas': Promotion.objects.filter(is_active=True).count(),
        'usos_de_promocao': Promotion.objects.aggregate(t=Sum('redemptions_count'))['t'] or 0,
    }


class SummaryView(APIView):
    """Visão geral do financeiro. MRR = preço de TABELA das assinaturas ativas com Stripe (não desconta cupons nem reajustes)."""
    permission_classes = [IsStaff]

    def get(self, request):
        return Response(finance_summary())


router = DefaultRouter()
router.register('plans', PlanViewSet, basename='admin-plans')
router.register('packs', PackViewSet, basename='admin-packs')
router.register('promotions', PromotionViewSet, basename='admin-promotions')
router.register('notices', NoticeViewSet, basename='admin-notices')
router.register('credit-weights', WeightViewSet, basename='admin-credit-weights')
