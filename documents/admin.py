from django.contrib import admin

from .models import ClientDocument, Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "nome", "tipo", "status", "data", "organization", "created_at")
    list_filter = ("tipo", "status", "organization")
    search_fields = ("nome",)


@admin.register(ClientDocument)
class ClientDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "nome_cliente", "documento", "created_at")
    # nome do cliente é cifrado: a busca usa o índice de tokens (core/pii.py)
    search_fields = ()

    def get_search_results(self, request, queryset, search_term):
        from core.pii import filter_by_term
        if not search_term.strip():
            return queryset, False
        return filter_by_term(queryset, "nome_cliente_idx", "client.name", search_term), False
    raw_id_fields = ("documento",)
