from django.utils import timezone
from rest_framework import serializers

from .models import ClientDocument, Document


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "nome",
            "tipo",
            "status",
            "arquivo",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "arquivo": {"write_only": True, "required": True},
            "nome": {"required": True},
            "tipo": {"required": True},
            "status": {"required": True},
        }


class ClientDocumentCreateSerializer(DocumentSerializer):
    """Mesmo payload do documento + nome_cliente."""

    nome_cliente = serializers.CharField(max_length=255, write_only=True)

    class Meta(DocumentSerializer.Meta):
        fields = DocumentSerializer.Meta.fields + ["nome_cliente"]


def document_response_payload(doc, cliente=None):
    return {
        "id": doc.id,
        "nome": doc.nome,
        "cliente": cliente if cliente is not None else getattr(doc, "cliente", None),
        "tipo": doc.tipo,
        "data": doc.data.isoformat() if doc.data else None,
        "status": doc.status,
    }


def save_document(*, serializer, organization, uploaded_by):
    """Persiste Document; data e uploaded_by vêm do servidor / JWT."""
    from notifications.services import notify_document_uploaded

    doc = serializer.save(
        organization=organization,
        uploaded_by=uploaded_by,
        data=timezone.now(),
    )
    notify_document_uploaded(doc)
    return doc


def save_client_document(*, serializer, organization, uploaded_by):
    """
    Reutiliza save_document e cria o vínculo ClientDocument.
    serializer deve ser ClientDocumentCreateSerializer validado.
    """
    nome_cliente = serializer.validated_data.pop("nome_cliente")
    doc = save_document(
        serializer=serializer,
        organization=organization,
        uploaded_by=uploaded_by,
    )
    link = ClientDocument.objects.create(
        nome_cliente=nome_cliente,
        documento=doc,
    )
    return doc, link
