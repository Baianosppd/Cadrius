from django.contrib import admin

from compliance.models import ComplianceSnapshot, ControlAssessment


@admin.register(ControlAssessment)
class ControlAssessmentAdmin(admin.ModelAdmin):
    list_display = ('framework', 'control_id', 'status', 'owner', 'reviewed_at', 'next_review_at')
    list_filter = ('framework', 'status')
    search_fields = ('control_id', 'owner')


@admin.register(ComplianceSnapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'framework', 'score')
    list_filter = ('framework',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
