from django.db.models import OuterRef, Subquery
from django.http import FileResponse, Http404
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership

from .models import ClientDocument, Document
from .serializers import (
    ClientDocumentCreateSerializer,
    DocumentSerializer,
    document_response_payload,
    save_client_document,
    save_document,
)


def _org_documents_qs(user):
    membership = get_active_membership(user)
    if membership is None:
        return Document.objects.none()
    return Document.objects.filter(organization=membership.organization)


class DocumentPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


# query param -> lookup no queryset; novos filtros entram aqui
DOCUMENT_LIST_FILTERS = {
    "nome": "nome__icontains",
}


class DocumentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/v1/documentos/?nome=&page=&page_size=  — lista paginada
    POST /api/v1/documentos/                        — multipart: nome, tipo, status, arquivo
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DocumentSerializer
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = DocumentPagination

    def get_queryset(self):
        first_client = ClientDocument.objects.filter(
            documento=OuterRef("pk"),
        ).order_by("created_at", "id").values("nome_cliente")[:1]

        qs = _org_documents_qs(self.request.user).annotate(
            cliente=Subquery(first_client),
        )

        filters = {}
        for param, lookup in DOCUMENT_LIST_FILTERS.items():
            value = (self.request.query_params.get(param) or "").strip()
            if value:
                filters[lookup] = value
        qs = qs.filter(**filters)

        # ?cliente=silv  — busca parcial pelo nome do cliente (cifrado em repouso; usa o índice de tokens, ver core/pii.py)
        cliente = (self.request.query_params.get("cliente") or "").strip()
        if cliente:
            from core.pii import filter_by_term
            matches = filter_by_term(ClientDocument.objects.all(), "nome_cliente_idx", "client.name", cliente)
            qs = qs.filter(pk__in=matches.values("documento_id"))
        return qs

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        data = [document_response_payload(doc) for doc in page]
        return self.get_paginated_response(data)

    def create(self, request, *args, **kwargs):
        membership = get_active_membership(request.user)
        if membership is None:
            return Response(
                {"detail": "Utilizador sem organização ativa."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = save_document(
            serializer=serializer,
            organization=membership.organization,
            uploaded_by=request.user,
        )
        return Response(
            document_response_payload(doc),
            status=status.HTTP_201_CREATED,
        )


class ClientDocumentCreateView(APIView):
    """
    POST /api/v1/documentos/cliente/
    Mesmo multipart do documento + nome_cliente.
    """

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        membership = get_active_membership(request.user)
        if membership is None:
            return Response(
                {"detail": "Utilizador sem organização ativa."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ClientDocumentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc, link = save_client_document(
            serializer=serializer,
            organization=membership.organization,
            uploaded_by=request.user,
        )
        return Response(
            document_response_payload(doc, cliente=link.nome_cliente),
            status=status.HTTP_201_CREATED,
        )


class DocumentDownloadView(APIView):
    """GET /api/v1/documentos/{id}/download/ — ficheiro do documento."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        doc = _org_documents_qs(request.user).filter(pk=pk).first()
        if doc is None or not doc.arquivo:
            raise Http404

        try:
            file_handle = doc.arquivo.open("rb")
        except FileNotFoundError as exc:
            raise Http404 from exc

        filename = doc.arquivo.name.rsplit("/", 1)[-1]
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=filename,
        )


# ----------------------------------------------------------------------------- leitura automática (CAD-163)
def _extraction_payload(extraction):
    return {
        "status": extraction.status,
        "stage": extraction.stage,
        "message": extraction.message,
        "detected_kind": extraction.detected_kind,
        "text_chars": extraction.text_chars,
        "ocr_used": extraction.ocr_used,
        "provider": extraction.provider,
        "confidence": extraction.confidence,
        "fields": extraction.fields or {},
        "reviewed_at": extraction.reviewed_at,
        "reviewed_by": extraction.reviewed_by.email if extraction.reviewed_by_id else None,
    }


def _extraction_for(request, pk):
    from .models import DocumentExtraction

    doc = _org_documents_qs(request.user).filter(pk=pk).first()
    if doc is None:
        raise Http404
    extraction, _ = DocumentExtraction.objects.get_or_create(document=doc)
    return doc, extraction


def _can_review(user):
    membership = get_active_membership(user)
    return membership is not None and membership.role != "VIEWER"


class DocumentExtractionView(APIView):
    """GET /api/v1/documentos/{id}/extraction/ — situação da leitura automática e dados extraídos."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        _, extraction = _extraction_for(request, pk)
        return Response(_extraction_payload(extraction))


class DocumentExtractionReprocessView(APIView):
    """POST /api/v1/documentos/{id}/extraction/reprocess/ — roda a leitura de novo (não mexe no que já foi confirmado)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        from .models import DocumentExtraction
        from .pipeline import enqueue_processing

        if not _can_review(request.user):
            return Response({"detail": "Seu papel não permite reprocessar documentos."}, status=status.HTTP_403_FORBIDDEN)
        doc, extraction = _extraction_for(request, pk)
        if extraction.status == DocumentExtraction.Status.CONFIRMED:
            return Response({"detail": "Esta leitura já foi confirmada."}, status=status.HTTP_409_CONFLICT)
        if extraction.status in (DocumentExtraction.Status.PENDING, DocumentExtraction.Status.PROCESSING):
            return Response(_extraction_payload(extraction), status=status.HTTP_202_ACCEPTED)
        extraction.status, extraction.message = DocumentExtraction.Status.PENDING, "Na fila para nova leitura."
        extraction.save(update_fields=["status", "message", "updated_at"])
        enqueue_processing(doc.pk, request.user.pk)
        return Response(_extraction_payload(extraction), status=status.HTTP_202_ACCEPTED)


class DocumentExtractionConfirmView(APIView):
    """POST /api/v1/documentos/{id}/extraction/confirm/ {fields: {...}} — a pessoa revisa/corrige e confirma; prazos com data viram tarefas."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        from .models import DocumentExtraction
        from .pipeline import confirm

        if not _can_review(request.user):
            return Response({"detail": "Seu papel não permite confirmar leituras."}, status=status.HTTP_403_FORBIDDEN)
        _, extraction = _extraction_for(request, pk)
        if extraction.status not in (DocumentExtraction.Status.REVIEW, DocumentExtraction.Status.CONFIRMED):
            return Response({"detail": "Não há leitura pronta para confirmar."}, status=status.HTTP_409_CONFLICT)
        edited = request.data.get("fields") or {}
        if not isinstance(edited, dict):
            return Response({"fields": ["Envie um objeto com os campos revisados."]}, status=status.HTTP_400_BAD_REQUEST)
        tasks = confirm(extraction, request.user, edited)
        payload = _extraction_payload(extraction)
        payload["tasks_created"] = [{"id": t.pk, "titulo": t.titulo, "scheduled_at": t.scheduled_at} for t in tasks]
        return Response(payload)


class DocumentDetailView(APIView):
    """GET /api/v1/documentos/{id}/ — dados do documento (a leitura automática está em /extraction/)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        doc = _org_documents_qs(request.user).filter(pk=pk).first()
        if doc is None:
            raise Http404
        link = ClientDocument.objects.filter(documento=doc).order_by("created_at", "id").first()
        payload = document_response_payload(doc, cliente=link.nome_cliente if link else None)
        payload["tem_arquivo"] = bool(doc.arquivo)
        return Response(payload)
