from django.contrib import admin
from .models import (SubscriptionPlan, AIUsageLog, MemberCreditUsage, CreditPack, CreditLot, Promotion, PromotionRedemption,
                     BillingNotice, CreditWeight, PlanPriceHistory)

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'price_brl', 'max_ai_extractions', 'is_active')
    list_filter = ('is_active', 'tier')
    search_fields = ('name',)
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('name', 'tier', 'is_active')
        }),
        ('Limites e Quotas B2B', {
            'fields': ('max_users', 'max_ai_extractions'),
        }),
        ('Financeiro', {
            'fields': ('price_brl',),
        }),
    )

@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ('organization', 'billing_cycle_month', 'extractions_count', 'limite_atingido')
    list_filter = ('billing_cycle_month',)
    search_fields = ('organization__name',)
    readonly_fields = ('organization', 'billing_cycle_month', 'extractions_count')
    
    @admin.display(boolean=True, description='Atingiu o Limite?')
    def limite_atingido(self, obj):
        try:
            limite = obj.organization.plan.max_ai_extractions
            return obj.extractions_count >= limite
        except AttributeError:
            return False


@admin.register(MemberCreditUsage)
class MemberCreditUsageAdmin(admin.ModelAdmin):
    list_display = ('membership', 'billing_cycle_month', 'credits_used')
    list_filter = ('billing_cycle_month',)
    search_fields = ('membership__user__email', 'membership__organization__name')
    readonly_fields = ('membership', 'billing_cycle_month', 'credits_used')


@admin.register(CreditPack)
class CreditPackAdmin(admin.ModelAdmin):
    list_display = ('name', 'credits', 'price_brl', 'is_active')
    list_filter = ('is_active',)


@admin.register(CreditLot)
class CreditLotAdmin(admin.ModelAdmin):
    list_display = ('organization', 'credits_total', 'credits_remaining', 'expires_at', 'created_at')
    search_fields = ('organization__name', 'stripe_session_id')
    readonly_fields = ('stripe_session_id',)


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'value', 'duration', 'redemptions_count', 'max_redemptions', 'is_active', 'ends_at')
    list_filter = ('is_active', 'kind', 'duration')
    search_fields = ('code', 'name')


@admin.register(PromotionRedemption)
class PromotionRedemptionAdmin(admin.ModelAdmin):
    list_display = ('promotion', 'organization', 'created_at')
    readonly_fields = ('promotion', 'organization', 'stripe_session_id', 'created_at')


@admin.register(BillingNotice)
class BillingNoticeAdmin(admin.ModelAdmin):
    list_display = ('title', 'severity', 'is_active', 'starts_at', 'ends_at')
    list_filter = ('is_active', 'severity')


@admin.register(CreditWeight)
class CreditWeightAdmin(admin.ModelAdmin):
    list_display = ('operation', 'label', 'credits', 'is_active')


@admin.register(PlanPriceHistory)
class PlanPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('plan', 'old_price', 'new_price', 'old_credits', 'new_credits', 'changed_by', 'changed_at')
    readonly_fields = [f.name for f in PlanPriceHistory._meta.fields]
