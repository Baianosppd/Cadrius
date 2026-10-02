from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from audit import service as audit
from privacy import consent, dsr
from privacy.models import ConsentRecord, DataSubjectRequest, LegalDocument, SubprocessorEntry
from privacy.serializers import (
    ConsentCreateSerializer, ConsentRecordSerializer, DataSubjectRequestSerializer,
    LegalDocumentSerializer, SubprocessorSerializer,
)


class CurrentDocumentsView(generics.ListAPIView):
    """GET /api/v1/legal/documents/ — versões vigentes (público: o cadastro precisa exibi-las)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = LegalDocumentSerializer
    pagination_class = None

    def get_queryset(self):
        return LegalDocument.objects.filter(is_current=True).order_by('kind')


class SubprocessorListView(generics.ListAPIView):
    """GET /api/v1/legal/subprocessors/ — lista pública de suboperadores (transparência, art. 9º)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    serializer_class = SubprocessorSerializer
    pagination_class = None
    queryset = SubprocessorEntry.objects.filter(active=True)


class MyConsentsView(APIView):
    """GET /api/v1/legal/consents/me/ — aceites do utilizador e documentos pendentes."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        records = ConsentRecord.objects.filter(user_ref=str(request.user.pk)).select_related('document')
        return Response({
            'consents': ConsentRecordSerializer(records, many=True).data,
            'pending': LegalDocumentSerializer(consent.pending_documents(request.user), many=True).data,
        })


class ConsentCreateView(APIView):
    """
    POST /api/v1/legal/consents/ — registra aceite/revogação.
    Documentos essenciais (termos/política/ciência) só podem ser revogados encerrando a conta.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ConsentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = serializer.validated_data['document_id']
        granted = serializer.validated_data['granted']
        purpose = serializer.validated_data['purpose']

        if not granted and doc.kind in {k.value for k in consent.REQUIRED_KINDS}:
            return Response(
                {'detail': 'Documentos essenciais não podem ser revogados isoladamente. '
                           'Para encerrar o tratamento, abra um pedido de eliminação da conta.',
                 'code': 'essential_document'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership = get_active_membership(request.user)
        record = consent.record_consent(
            request.user, doc, granted=granted, purpose=purpose, method='api',
            organization=membership.organization if membership else None,
        )
        return Response(ConsentRecordSerializer(record).data, status=status.HTTP_201_CREATED)


class PrivacyRequestListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/privacy/requests/ — pedidos do titular (art. 18)."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DataSubjectRequestSerializer
    pagination_class = None

    def get_queryset(self):
        return DataSubjectRequest.objects.filter(user_ref=str(self.request.user.pk))

    def perform_create(self, serializer):
        membership = get_active_membership(self.request.user)
        serializer.instance = dsr.open_request(
            self.request.user, serializer.validated_data['type'], serializer.validated_data.get('notes', ''),
            organization=membership.organization if membership else None,
        )


class MyDataExportView(APIView):
    """GET /api/v1/privacy/me/export/ — cópia dos dados do próprio titular (acesso/portabilidade)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(dsr.export_user_data(request.user))


class OrganizationClosureView(APIView):
    """POST /api/v1/privacy/organization/close/ — OWNER encerra o escritório (eliminação em 30 dias)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        membership = get_active_membership(request.user)
        if membership is None or membership.role != 'OWNER':
            audit.log('permission.denied', outcome='denied', reason='encerramento de organização sem ser OWNER')
            return Response({'detail': 'Apenas o dono do escritório pode encerrá-lo.'}, status=status.HTTP_403_FORBIDDEN)
        if request.data.get('confirm') != membership.organization.name:
            return Response({'detail': 'Confirme enviando o nome exato do escritório em "confirm".'},
                            status=status.HTTP_400_BAD_REQUEST)
        off = dsr.request_organization_closure(membership.organization, request.user)
        return Response({'status': 'closure_scheduled', 'purge_after': off.purge_after}, status=status.HTTP_202_ACCEPTED)
