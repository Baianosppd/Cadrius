from django.contrib import admin

from aigov.guard import set_global_switch
from aigov.models import AIActionLog, AIGovernancePolicy, GlobalAISwitch


@admin.register(AIGovernancePolicy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ('organization', 'ai_enabled', 'autonomy_level', 'daily_ai_request_limit', 'updated_at')
    list_filter = ('ai_enabled', 'autonomy_level')


@admin.register(GlobalAISwitch)
class GlobalSwitchAdmin(admin.ModelAdmin):
    list_display = ('ai_enabled', 'reason', 'changed_by', 'changed_at')

    def has_add_permission(self, request):
        return not GlobalAISwitch.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):  # passa pelo guard: limpa cache e audita
        set_global_switch(obj.ai_enabled, reason=obj.reason, changed_by=str(request.user.pk))


@admin.register(AIActionLog)
class ActionLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'organization_id', 'kind', 'provider', 'success', 'blocked', 'block_reason')
    list_filter = ('kind', 'provider', 'blocked', 'success')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
