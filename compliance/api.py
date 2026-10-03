"""API JSON do Centro de Segurança — para o front-end React (equipe de segurança/staff)."""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from aigov.guard import global_ai_enabled
from aigov.models import AIActionLog
from audit.models import AnomalyAlert, AuditEvent
from audit.permissions import IsPlatformStaff
from audit.verify import verify_chain
from compliance import engine
from compliance.catalog import CATALOG, FRAMEWORKS
from compliance.ropa import PROCESSING_ACTIVITIES


def _row(r: engine.Row) -> dict:
    a = r.assessment
    return {
        'id': r.control.id, 'theme': r.control.theme, 'title': r.control.title, 'status': r.status, 'label': r.label,
        'source': r.source, 'evidence': r.control.evidence,
        'checks': [{'name': n, 'title': t, 'status': res.status, 'detail': res.detail} for n, t, res in r.auto],
        'assessment': {'owner': a.owner, 'evidence_url': a.evidence_url, 'justification': a.justification,
                       'reviewed_at': a.reviewed_at, 'next_review_at': a.next_review_at} if a else None,
    }


class OverviewApi(APIView):
    """GET /api/v1/security/overview/ — cartões da tela inicial do Centro de Segurança."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        data = engine.evaluate_all()
        day = timezone.now() - timedelta(hours=24)
        events = AuditEvent.objects.filter(occurred_at__gte=day)
        chain = verify_chain()
        return Response({
            'overall_score': data['_overall'],
            'frameworks': {fw: {'title': FRAMEWORKS[fw], 'score': data[fw]['score'], 'counts': data[fw]['counts']}
                           for fw in CATALOG},
            'audit': {'chain_ok': chain['ok'], 'chain_checked': chain['checked'], 'events_24h': events.count(),
                      'denied_24h': events.filter(outcome='denied').count(),
                      'failed_logins_24h': events.filter(action='auth.login.failure').count()},
            'alerts_open': {s: AnomalyAlert.objects.filter(status='open', severity=s).count()
                            for s in ('critical', 'high', 'medium', 'low')},
            'ai': {'global_enabled': global_ai_enabled(),
                   'requests_24h': AIActionLog.objects.filter(created_at__gte=day, blocked=False).count(),
                   'blocked_24h': AIActionLog.objects.filter(created_at__gte=day, blocked=True).count()},
            'failing_checks': [{'name': n, 'title': engine.checks_module.TITLES[n], 'detail': r.detail}
                               for n, r in data['_checks'].items() if r.status == 'fail'],
        })


class ControlsApi(APIView):
    """GET /api/v1/security/controls/?framework=iso27001|iso27701|lgpd[&status=...]"""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        framework = request.query_params.get('framework', 'iso27001')
        if framework not in CATALOG:
            return Response({'detail': 'framework inválido', 'allowed': list(CATALOG)}, status=400)
        rows = engine.evaluate(framework)
        status = request.query_params.get('status')
        summary = engine.score(rows)
        if status:
            rows = [r for r in rows if r.status == status]
        return Response({'framework': framework, 'title': FRAMEWORKS[framework], **summary,
                         'controls': [_row(r) for r in rows]})


class ChecksApi(APIView):
    """GET /api/v1/security/checks/ — verificações automáticas de postura técnica."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        results = engine.checks_module.run_all()
        return Response([{'name': n, 'title': engine.checks_module.TITLES[n], 'status': r.status, 'detail': r.detail}
                         for n, r in results.items()])


class RopaApi(APIView):
    """GET /api/v1/security/ropa/ — registro das operações de tratamento (LGPD art. 37)."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        return Response(PROCESSING_ACTIVITIES)
