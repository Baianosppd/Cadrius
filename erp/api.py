"""API do conector de ERP (CAD-167). Prefixo: /api/v1/erp/ — gestão do conector: OWNER/ADMIN; executar: membros (VIEWER só simula)."""
from __future__ import annotations

from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from erp import engine
from erp.models import ErpCallLog, ErpConnector
from erp.presets import PRESETS
from integrations.ssrf import UnsafeURLError, validate_outbound_url


class ConnectorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    preset = serializers.ChoiceField(choices=list(PRESETS))
    base_url = serializers.URLField(max_length=300)
    token = serializers.CharField(max_length=2000, required=False, allow_blank=True, write_only=True)
    operations = serializers.DictField(required=False)
    live_enabled = serializers.BooleanField(required=False)

    def validate_base_url(self, value):
        try:
            validate_outbound_url(value, resolve=False)
        except UnsafeURLError as exc:
            raise serializers.ValidationError(str(exc))
        if not value.startswith('https://') and not self.context.get('allow_http'):
            raise serializers.ValidationError('Use HTTPS.')
        return value.rstrip('/')

    def validate_operations(self, value):
        try:
            for name, spec in value.items():
                engine.validate_operation(name, spec)
        except engine.ErpError as exc:
            raise serializers.ValidationError(str(exc))
        return value


def _json(c):
    return {'id': c.pk, 'name': c.name, 'preset': c.preset, 'base_url': c.base_url, 'has_credentials': bool((c.credentials or {}).get('token')),
            'live_enabled': c.live_enabled, 'is_active': c.is_active, 'operations': sorted(engine.operations_of(c))}


def _ctx(request):
    m = get_active_membership(request.user)
    return m


class PresetsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response([{'preset': k, 'label': v['label'], 'base_url_hint': v['base_url_hint'], 'operations': sorted(v['operations'])}
                         for k, v in PRESETS.items()])


class ConnectorListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        m = _ctx(request)
        if m is None:
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response([_json(c) for c in ErpConnector.objects.filter(organization=m.organization)])

    def post(self, request):
        m = _ctx(request)
        if m is None or m.role not in MANAGE_TEAM_ROLES:
            return Response({'detail': 'Apenas dono/administrador configura o ERP.'}, status=status.HTTP_403_FORBIDDEN)
        from django.conf import settings
        ser = ConnectorSerializer(data=request.data, context={'allow_http': getattr(settings, 'OUTBOUND_ALLOW_PRIVATE_NETWORKS', False)})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        if ErpConnector.objects.filter(organization=m.organization, name=d['name']).exists():
            return Response({'detail': 'Já existe um conector com este nome.'}, status=status.HTTP_409_CONFLICT)
        c = ErpConnector.objects.create(organization=m.organization, name=d['name'], preset=d['preset'], base_url=d['base_url'],
                                        credentials={'token': d['token']} if d.get('token') else {}, operations=d.get('operations', {}),
                                        live_enabled=False, created_by=request.user)   # sempre nasce só-simulação
        audit.log('connection.created', actor=request.user, organization=m.organization, target=c,
                  changes={'app_name': f'ERP:{c.preset}'}, data_categories=['credenciais'])
        return Response(_json(c), status=status.HTTP_201_CREATED)


class ConnectorDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get(self, request, pk):
        m = _ctx(request)
        if m is None:
            return None, None
        return m, ErpConnector.objects.filter(organization=m.organization, pk=pk).first()

    def patch(self, request, pk):
        """Só dono/admin: ativar/desativar execução real e trocar o token."""
        m, c = self._get(request, pk)
        if c is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if m.role not in MANAGE_TEAM_ROLES:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if 'live_enabled' in request.data:
            c.live_enabled = bool(request.data['live_enabled'])
        if request.data.get('token'):
            c.credentials = {'token': str(request.data['token'])[:2000]}
        c.save()
        audit.log('connection.updated', actor=request.user, organization=m.organization, target=c,
                  changes={'live_enabled': c.live_enabled}, data_categories=['credenciais'])
        return Response(_json(c))

    def delete(self, request, pk):
        m, c = self._get(request, pk)
        if c is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if m.role not in MANAGE_TEAM_ROLES:
            return Response(status=status.HTTP_403_FORBIDDEN)
        audit.log('connection.deleted', actor=request.user, organization=m.organization, target=c, changes={'app_name': f'ERP:{c.preset}'})
        c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RunOperationView(ConnectorDetailView):
    """POST {operation, data, dry_run=true, confirm=false}. Padrão SEMPRE simulação; real só com live_enabled (+ confirm se alterar o ERP)."""

    def post(self, request, pk):
        m, c = self._get(request, pk)
        if c is None or not c.is_active:
            return Response(status=status.HTTP_404_NOT_FOUND)
        dry_run = request.data.get('dry_run', True) is not False
        if not dry_run and m.role == 'VIEWER':
            return Response({'detail': 'Seu perfil só permite simulação.'}, status=status.HTTP_403_FORBIDDEN)
        operation = str(request.data.get('operation', ''))
        data = request.data.get('data') if isinstance(request.data.get('data'), dict) else {}
        confirmed = request.data.get('confirm') is True
        log = ErpCallLog(connector=c, operation=operation[:60], dry_run=dry_run, actor=request.user)
        try:
            result = engine.run(c, operation, data, dry_run=dry_run, confirmed=confirmed)
        except engine.ErpError as exc:
            log.error = str(exc)[:300]
            log.save()
            return Response({'detail': str(exc), 'code': exc.code}, status=status.HTTP_400_BAD_REQUEST if exc.code != 'unreachable' else status.HTTP_502_BAD_GATEWAY)
        log.ok, log.status_code = result.get('ok', True), result['status_code']
        log.save()
        if not dry_run:
            audit.log('integration.call', actor=request.user, organization=m.organization, target=c,
                      changes={'erp': c.preset, 'operation': operation, 'status': result['status_code']},
                      data_categories=['dados_processuais'], legal_basis='execucao_contrato')
        return Response(result)
