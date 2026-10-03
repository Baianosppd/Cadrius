from django.contrib import admin, messages

from privacy import dsr
from privacy.models import (
    ConsentRecord, DataSubjectRequest, LegalDocument, OrganizationOffboarding, SubprocessorEntry,
)


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ('kind', 'version', 'is_current', 'needs_legal_review', 'published_at', 'content_sha256')
    list_filter = ('kind', 'is_current', 'needs_legal_review')

    def get_readonly_fields(self, request, obj=None):
        # Publicado = imutável (texto/título): mudou o texto, publique nova versão.
        return ('content_sha256', 'title', 'content_md', 'kind', 'version') if obj else ('content_sha256',)


@admin.register(ConsentRecord)
class ConsentRecordAdmin(admin.ModelAdmin):
    list_display = ('occurred_at', 'user_ref', 'document', 'purpose', 'granted', 'method')
    list_filter = ('granted', 'document__kind')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SubprocessorEntry)
class SubprocessorAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'international_transfer', 'contract_verified', 'active')
    list_filter = ('international_transfer', 'contract_verified', 'active')


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(admin.ModelAdmin):
    list_display = ('opened_at', 'type', 'status', 'due_at', 'user_ref', 'handled_by')
    list_filter = ('status', 'type')
    readonly_fields = ('user_ref', 'opened_at', 'due_at', 'fulfilled_at', 'handled_by')
    actions = ['mark_fulfilled', 'mark_rejected']

    @admin.action(description='Atender (executa eliminação/anonimização quando aplicável)')
    def mark_fulfilled(self, request, queryset):
        for req in queryset.exclude(status__in=['fulfilled', 'rejected']):
            dsr.fulfill_request(req, handler_id=str(request.user.pk), resolution='Atendido via Admin')
        self.message_user(request, 'Pedidos atendidos.', messages.SUCCESS)

    @admin.action(description='Recusar (exige justificativa no campo "resolution")')
    def mark_rejected(self, request, queryset):
        for req in queryset.exclude(status__in=['fulfilled', 'rejected']):
            if not req.resolution:
                self.message_user(request, f'Pedido {req.pk}: preencha a justificativa antes de recusar.', messages.ERROR)
                continue
            dsr.reject_request(req, handler_id=str(request.user.pk), resolution=req.resolution)


@admin.register(OrganizationOffboarding)
class OffboardingAdmin(admin.ModelAdmin):
    list_display = ('organization_name', 'status', 'requested_at', 'purge_after')
    list_filter = ('status',)
