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
    search_fields = ("nome_cliente",)
    raw_id_fields = ("documento",)
