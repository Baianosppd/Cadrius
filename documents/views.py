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
        return qs.filter(**filters)

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
