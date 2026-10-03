"""API de conexões (AppConnection) — usada pelo front para escolher/criar a conexão de um gatilho de workflow."""
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from accounts.permissions import OrgRolePermission
from accounts.tenancy import resolve_request_tenant
from audit import service as audit
from integrations.models import AppConnection

MAX_CREDENTIAL_KEYS = 20
MAX_CREDENTIAL_VALUE_LEN = 2000


class ConnectionSerializer(serializers.ModelSerializer):
    # As credenciais são SOMENTE ESCRITA: nunca voltam em nenhuma resposta (nem cifradas).
    credentials = serializers.DictField(
        child=serializers.CharField(allow_blank=True, max_length=MAX_CREDENTIAL_VALUE_LEN),
        write_only=True, required=False,
    )
    app_label = serializers.CharField(source='get_app_name_display', read_only=True)
    has_credentials = serializers.SerializerMethodField()

    class Meta:
        model = AppConnection
        fields = ['id', 'name', 'app_name', 'app_label', 'credentials', 'has_credentials', 'is_active', 'created_at']
        read_only_fields = ['id', 'app_label', 'has_credentials', 'created_at']

    def get_has_credentials(self, obj) -> bool:
        return bool(obj.credentials)

    def validate_credentials(self, value):
        if len(value) > MAX_CREDENTIAL_KEYS:
            raise serializers.ValidationError('Credenciais demais.')
        return value

    def validate(self, attrs):
        request = self.context['request']
        name = attrs.get('name')
        if name and AppConnection.objects.filter(user=request.user, name=name).exclude(
                pk=getattr(self.instance, 'pk', None)).exists():
            raise serializers.ValidationError({'name': 'Você já tem uma conexão com este nome.'})
        return attrs


class ConnectionListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/v1/connections/ — conexões dos membros ativos do escritório (sem credenciais)."""

    permission_classes = [OrgRolePermission]
    serializer_class = ConnectionSerializer
    pagination_class = None

    def get_queryset(self):
        tenant = resolve_request_tenant(self.request)
        if tenant is None:
            return AppConnection.objects.filter(user=self.request.user).order_by('name')
        member_ids = tenant.members.filter(is_active=True).values_list('user_id', flat=True)
        return AppConnection.objects.filter(user_id__in=member_ids).order_by('name')

    def perform_create(self, serializer):
        connection = serializer.save(user=self.request.user)
        audit.log('connection.created', target=connection, changes={'app_name': connection.app_name},
                  data_categories=['credenciais'])


class ConnectionDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/connections/<id>/ — só o dono da conexão remove."""

    permission_classes = [OrgRolePermission]

    def get_queryset(self):
        return AppConnection.objects.filter(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        connection = self.get_object()
        audit.log('connection.deleted', target=connection, changes={'app_name': connection.app_name})
        connection.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
