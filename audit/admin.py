from django.contrib import admin

from audit.models import AnomalyAlert, AuditChainHead, AuditCheckpoint, AuditEvent


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(ReadOnlyAdmin):
    list_display = ('seq', 'occurred_at', 'action', 'outcome', 'actor_type', 'actor_label', 'organization_id', 'ip')
    list_filter = ('outcome', 'actor_type', 'action')
    search_fields = ('request_id', 'actor_id', 'target_id', 'action')
    date_hierarchy = 'occurred_at'


@admin.register(AuditCheckpoint)
class AuditCheckpointAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'purged_until_seq', 'purged_count', 'reason')


@admin.register(AuditChainHead)
class AuditChainHeadAdmin(ReadOnlyAdmin):
    list_display = ('last_seq', 'last_hash')


@admin.register(AnomalyAlert)
class AnomalyAlertAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'severity', 'rule', 'status', 'actor_label', 'ip', 'summary')
    list_filter = ('severity', 'status', 'rule')
    readonly_fields = tuple(f.name for f in AnomalyAlert._meta.fields if f.name not in ('status',))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
