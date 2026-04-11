from django.contrib import admin
from .models import SubscriptionPlan, AIUsageLog

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
    search_fields = ('organization__name', 'organization__cnpj')
    readonly_fields = ('organization', 'billing_cycle_month', 'extractions_count')
    
    @admin.display(boolean=True, description='Atingiu o Limite?')
    def limite_atingido(self, obj):
        try:
            limite = obj.organization.plan.max_ai_extractions
            return obj.extractions_count >= limite
        except AttributeError:
            return False