import csv
from datetime import timedelta

from django.db.models import Count
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.tenancy import resolve_request_tenant
from audit import service
from audit.models import AnomalyAlert, AuditEvent
from audit.permissions import IsOrganizationAdmin
from audit.serializers import AnomalyAlertSerializer, AuditEventSerializer

EXPORT_LIMIT = 10_000


def filter_events(queryset, params):
    """Filtros comuns da API: action, outcome, actor_id, from, to, q (prefixo de ação)."""
    if params.get('action'):
        queryset = queryset.filter(action=params['action'])
    if params.get('prefix'):
        queryset = queryset.filter(action__startswith=params['prefix'])
    if params.get('outcome'):
        queryset = queryset.filter(outcome=params['outcome'])
    if params.get('actor_id'):
        queryset = queryset.filter(actor_id=params['actor_id'])
    if params.get('from') and (dt := parse_datetime(params['from'])):
        queryset = queryset.filter(occurred_at__gte=dt)
    if params.get('to') and (dt := parse_datetime(params['to'])):
        queryset = queryset.filter(occurred_at__lte=dt)
    return queryset


class OrgEventsMixin:
    permission_classes = [IsOrganizationAdmin]

    def org_events(self):
        tenant = resolve_request_tenant(self.request)
        if tenant is None:
            return AuditEvent.objects.none()
        return AuditEvent.objects.filter(organization_id=tenant.pk)


class AuditEventListView(OrgEventsMixin, generics.ListAPIView):
    """GET /api/v1/audit/events/ — trilha do escritório (OWNER/ADMIN)."""

    serializer_class = AuditEventSerializer

    def get_queryset(self):
        return filter_events(self.org_events(), self.request.query_params).order_by('-seq')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        service.log('audit.viewed', reason=request.get_full_path()[:255])
        return response


class _Echo:
    def write(self, value):
        return value


class AuditEventExportView(OrgEventsMixin, APIView):
    """GET /api/v1/audit/events/export/ — CSV (também fica auditado: audit.export)."""

    def get(self, request):
        qs = filter_events(self.org_events(), request.query_params).order_by('-seq')[:EXPORT_LIMIT]
        columns = ['seq', 'occurred_at', 'actor_type', 'actor_label', 'action', 'target_type',
                   'target_id', 'outcome', 'reason', 'ip', 'request_id', 'hash']
        service.log('audit.export', changes={'format': 'csv', 'filters': sorted(request.query_params)},
                    data_categories=['auditoria'])

        def rows():
            writer = csv.writer(_Echo())
            yield writer.writerow(columns)
            for e in qs.iterator(chunk_size=1000):
                # Prefixo ' evita injeção de fórmulas (CSV injection) ao abrir no Excel.
                yield writer.writerow([_safe(getattr(e, c)) for c in columns])

        response = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="auditoria.csv"'
        return response


def _safe(value):
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@') else text


class AuditSummaryView(OrgEventsMixin, APIView):
    """GET /api/v1/audit/summary/ — contagens dos últimos 7 dias (cards do painel)."""

    def get(self, request):
        since = timezone.now() - timedelta(days=7)
        events = self.org_events().filter(occurred_at__gte=since)
        by_action = dict(events.values_list('action').annotate(n=Count('seq')).order_by('-n')[:15])
        tenant = resolve_request_tenant(request)
        open_alerts = AnomalyAlert.objects.filter(organization_id=tenant.pk, status='open').count() if tenant else 0
        return Response({
            'window_days': 7,
            'total_events': events.count(),
            'failed_logins': events.filter(action='auth.login.failure').count(),
            'denied': events.filter(outcome='denied').count(),
            'exports': events.filter(action__in=['data.export', 'audit.export']).count(),
            'open_alerts': open_alerts,
            'by_action': by_action,
        })


class AlertListView(generics.ListAPIView):
    """GET /api/v1/audit/alerts/ — alertas de anomalia do escritório."""

    permission_classes = [IsOrganizationAdmin]
    serializer_class = AnomalyAlertSerializer

    def get_queryset(self):
        tenant = resolve_request_tenant(self.request)
        qs = AnomalyAlert.objects.filter(organization_id=tenant.pk) if tenant else AnomalyAlert.objects.none()
        if self.request.query_params.get('status'):
            qs = qs.filter(status=self.request.query_params['status'])
        return qs


class AlertReviewView(generics.UpdateAPIView):
    """PATCH /api/v1/audit/alerts/<id>/ — triagem (ack/resolved/false_positive)."""

    permission_classes = [IsOrganizationAdmin]
    serializer_class = AnomalyAlertSerializer
    http_method_names = ['patch']

    def get_queryset(self):
        tenant = resolve_request_tenant(self.request)
        return AnomalyAlert.objects.filter(organization_id=tenant.pk) if tenant else AnomalyAlert.objects.none()

    def perform_update(self, serializer):
        alert = serializer.save(reviewed_by=str(self.request.user.pk), reviewed_at=timezone.now())
        service.log('anomaly.reviewed', target=alert, changes={'status': alert.status})

    def patch(self, request, *args, **kwargs):
        if request.data.get('status') not in dict(AnomalyAlert.Status.choices):
            return Response({'status': ['Estado inválido.']}, status=status.HTTP_400_BAD_REQUEST)
        return super().patch(request, *args, **kwargs)
