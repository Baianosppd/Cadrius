"""Centro de Segurança — telas HTML (equipe de segurança/staff).

Renderizadas pelo próprio Django para estarem disponíveis já (login pelo Admin). O front-end React
pode substituí-las consumindo a API em ``/api/v1/security/`` (ver docs/PLANO_EQUIPES.md).
"""
from __future__ import annotations

import csv
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from aigov.guard import global_ai_enabled, set_global_switch
from aigov.models import AIActionLog, AIGovernancePolicy, GlobalAISwitch
from audit import service as audit
from audit.models import AnomalyAlert, AuditEvent
from audit.verify import verify_chain
from compliance import engine
from compliance.catalog import CATALOG, FRAMEWORKS, get_control
from compliance.models import ComplianceSnapshot, ControlAssessment
from compliance.ropa import PROCESSING_ACTIVITIES
from privacy.models import (
    ConsentRecord, DataSubjectRequest, LegalDocument, OrganizationOffboarding, SubprocessorEntry,
)
from workflows.models import ExecutionLog, Workflow


def staff_required(view):
    """Somente equipe (is_staff). Visitante vai ao login do Admin; usuário comum recebe 403 (e fica auditado)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect(f'/admin/login/?next={request.path}')
        if not (user.is_staff and user.is_active):
            audit.log('permission.denied', outcome='denied', reason=f'centro de segurança: {request.path}'[:255])
            return HttpResponseForbidden('Acesso restrito à equipe de segurança.')
        audit.log('audit.viewed', reason=f'centro de segurança: {request.path}'[:255])
        return view(request, *args, **kwargs)

    return wrapper


def _nav(active: str) -> dict:
    return {'active': active, 'frameworks': FRAMEWORKS}


def _csv_safe(value) -> str:
    text = '' if value is None else str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@') else text


# ------------------------------------------------------------------------------------------------ visão geral
@staff_required
def overview(request):
    data = engine.evaluate_all()
    now = timezone.now()
    day = now - timedelta(hours=24)
    events = AuditEvent.objects.filter(occurred_at__gte=day)
    chain = verify_chain()
    open_alerts = AnomalyAlert.objects.filter(status='open')

    failing = [(fw, r) for fw in ('iso27001', 'lgpd') for r in data[fw]['rows'] if r.status == engine.NOT_IMPLEMENTED]
    snapshots = {fw: ComplianceSnapshot.objects.filter(framework=fw)[:2] for fw in ('iso27001', 'iso27701', 'lgpd')}
    trend = {}
    for fw, snaps in snapshots.items():
        snaps = list(snaps)
        trend[fw] = round(snaps[0].score - snaps[1].score, 1) if len(snaps) == 2 else None

    ctx = {
        **_nav('overview'),
        'scores': [(fw, FRAMEWORKS[fw], data[fw]['score'], data[fw]['counts'], trend[fw])
                   for fw in ('iso27001', 'iso27701', 'lgpd')],
        'overall': data['_overall'],
        'chain': chain,
        'events_24h': events.count(),
        'denied_24h': events.filter(outcome='denied').count(),
        'failed_logins_24h': events.filter(action='auth.login.failure').count(),
        'locked_24h': events.filter(action='auth.login.locked').count(),
        'alerts_by_severity': {s: open_alerts.filter(severity=s).count() for s in ('critical', 'high', 'medium', 'low')},
        'recent_alerts': open_alerts.order_by('-created_at')[:6],
        'critical_events': AuditEvent.objects.filter(action__in=['auth.login.locked', 'permission.denied', 'audit.chain_broken',
                                                                'anomaly.detected', 'ai.blocked']).order_by('-seq')[:8],
        'failing_controls': failing[:10],
        'checks_failing': [(n, engine.checks_module.TITLES[n], r) for n, r in data['_checks'].items() if r.status == 'fail'],
        'ai': {
            'global_enabled': global_ai_enabled(),
            'requests_24h': AIActionLog.objects.filter(created_at__gte=day, blocked=False).count(),
            'blocked_24h': AIActionLog.objects.filter(created_at__gte=day, blocked=True).count(),
            'pending_reviews': ExecutionLog.objects.filter(status='PENDING_REVIEW').count(),
            'drafts_waiting': Workflow.objects.filter(ai_generated=True, approved_at__isnull=True).count(),
        },
        'privacy': {
            'dsr_open': DataSubjectRequest.objects.filter(status__in=['open', 'in_progress']).count(),
            'dsr_overdue': sum(1 for r in DataSubjectRequest.objects.filter(status__in=['open', 'in_progress']) if r.overdue),
            'docs_pending_review': LegalDocument.objects.filter(is_current=True, needs_legal_review=True).count(),
            'subprocessors_unverified': SubprocessorEntry.objects.filter(active=True, contract_verified=False).count(),
        },
        'env': {'debug': settings.DEBUG, 'app_version': getattr(settings, 'APP_VERSION', ''),
                'environment': getattr(settings, 'APP_VERSION', '') and ('desenvolvimento' if settings.DEBUG else 'produção')},
    }
    return render(request, 'securitycenter/overview.html', ctx)


# ------------------------------------------------------------------------------------------------ eventos
@staff_required
def events(request):
    qs = AuditEvent.objects.all().order_by('-seq')
    params = request.GET
    if params.get('prefix'):
        qs = qs.filter(action__startswith=params['prefix'])
    if params.get('outcome'):
        qs = qs.filter(outcome=params['outcome'])
    if params.get('actor'):
        qs = qs.filter(actor_label__icontains=params['actor']) | qs.filter(actor_id=params['actor'])
    if params.get('request_id'):
        qs = qs.filter(request_id=params['request_id'])
    if params.get('from') and (d := parse_date(params['from'])):
        qs = qs.filter(occurred_at__date__gte=d)
    if params.get('to') and (d := parse_date(params['to'])):
        qs = qs.filter(occurred_at__date__lte=d)

    page = Paginator(qs, 50).get_page(params.get('page'))
    query = params.copy()
    query.pop('page', None)
    ctx = {**_nav('events'), 'page': page, 'params': params, 'querystring': query.urlencode(),
           'prefixes': ['auth', 'admin', 'data', 'ai', 'workflow', 'mailbox', 'member', 'consent', 'dsr', 'anomaly',
                        'permission', 'ratelimit', 'webhook', 'audit', 'retention']}
    return render(request, 'securitycenter/events.html', ctx)


@staff_required
@require_POST
def verify_chain_view(request):
    result = verify_chain()
    if result['ok']:
        audit.log('audit.chain_verified', changes={'checked': result['checked'], 'by': 'security-center'})
        messages.success(request, f"Cadeia íntegra — {result['checked']} eventos verificados.")
    else:
        audit.log('audit.chain_broken', outcome='error', reason=result['reason'],
                  changes={'first_bad_seq': result['first_bad_seq']})
        messages.error(request, f"CADEIA ADULTERADA no evento #{result['first_bad_seq']}: {result['reason']}")
    return redirect('sc-events')


# ------------------------------------------------------------------------------------------------ alertas
@staff_required
def alerts(request):
    qs = AnomalyAlert.objects.all()
    status = request.GET.get('status', 'open')
    if status != 'all':
        qs = qs.filter(status=status)
    if request.GET.get('severity'):
        qs = qs.filter(severity=request.GET['severity'])
    ctx = {**_nav('alerts'), 'alerts': qs.order_by('-created_at')[:200], 'status': status,
           'severity': request.GET.get('severity', ''), 'statuses': AnomalyAlert.Status.choices,
           'counts': dict(AnomalyAlert.objects.values_list('status').annotate(n=Count('id')))}
    return render(request, 'securitycenter/alerts.html', ctx)


@staff_required
@require_POST
def alert_review(request, pk):
    alert = AnomalyAlert.objects.filter(pk=pk).first()
    status = request.POST.get('status')
    if alert is None or status not in dict(AnomalyAlert.Status.choices):
        messages.error(request, 'Alerta ou estado inválido.')
        return redirect('sc-alerts')
    alert.status, alert.reviewed_by, alert.reviewed_at = status, str(request.user.pk), timezone.now()
    alert.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    audit.log('anomaly.reviewed', target=alert, changes={'status': status})
    messages.success(request, f'Alerta #{alert.pk} marcado como "{alert.get_status_display()}".')
    return redirect(request.POST.get('next') or 'sc-alerts')


# ------------------------------------------------------------------------------------------------ frameworks
@staff_required
def framework(request, framework):
    if framework not in CATALOG:
        return HttpResponse('Norma desconhecida.', status=404)
    rows = engine.evaluate(framework)
    summary = engine.score(rows)
    status_filter = request.GET.get('status', '')
    if status_filter:
        rows = [r for r in rows if r.status == status_filter]
    ctx = {**_nav(framework), 'framework': framework, 'title': FRAMEWORKS[framework], 'groups': engine.by_theme(rows),
           'summary': summary, 'status_filter': status_filter, 'labels': engine.LABELS,
           'statuses': ControlAssessment.Status.choices,
           'snapshots': ComplianceSnapshot.objects.filter(framework=framework)[:12]}
    return render(request, 'securitycenter/framework.html', ctx)


@staff_required
@require_POST
def assess(request):
    framework, control_id = request.POST.get('framework'), request.POST.get('control_id')
    control = get_control(framework, control_id) if framework in CATALOG else None
    status = request.POST.get('status')
    if control is None or status not in dict(ControlAssessment.Status.choices):
        messages.error(request, 'Controle ou estado inválido.')
        return redirect('sc-overview')
    justification = request.POST.get('justification', '').strip()
    if status == 'not_applicable' and not justification:
        messages.error(request, 'Controle "não aplicável" exige justificativa.')
        return redirect('sc-framework', framework=framework)
    next_review = parse_date(request.POST.get('next_review_at', '') or '') if request.POST.get('next_review_at') else None
    ControlAssessment.objects.update_or_create(
        framework=framework, control_id=control_id,
        defaults={'status': status, 'owner': request.POST.get('owner', '')[:120],
                  'evidence_url': request.POST.get('evidence_url', '')[:500], 'justification': justification,
                  'reviewed_by': str(request.user.pk), 'reviewed_at': timezone.now(), 'next_review_at': next_review},
    )
    audit.log('compliance.assessment_updated', target_type='Control', target_id=f'{framework}:{control_id}',
              changes={'status': status})
    messages.success(request, f'Controle {control_id} atualizado.')
    return redirect(reverse('sc-framework', kwargs={'framework': framework}) + f'#c-{control_id}')


@staff_required
def framework_csv(request, framework):
    if framework not in CATALOG:
        return HttpResponse('Norma desconhecida.', status=404)
    rows = engine.evaluate(framework)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="conformidade-{framework}.csv"'
    writer = csv.writer(response)
    writer.writerow(['controle', 'tema', 'titulo', 'status', 'origem', 'verificacoes_automaticas', 'evidencia_no_sistema',
                     'responsavel', 'evidencia_url', 'justificativa', 'ultima_revisao'])
    for r in rows:
        a = r.assessment
        writer.writerow([_csv_safe(x) for x in (
            r.control.id, r.control.theme, r.control.title, r.label, r.source,
            '; '.join(f'{t}: {res.status} ({res.detail})' for _, t, res in r.auto), r.control.evidence,
            a.owner if a else '', a.evidence_url if a else '', a.justification if a else '',
            a.reviewed_at.date().isoformat() if a else '')])
    audit.log('data.export', changes={'scope': f'compliance:{framework}', 'format': 'csv'})
    return response


# ------------------------------------------------------------------------------------------------ postura técnica
@staff_required
def posture(request):
    results = engine.checks_module.run_all()
    used_by = {}
    for fw, controls in CATALOG.items():
        for c in controls:
            for name in c.checks:
                used_by.setdefault(name, []).append(f'{fw}:{c.id}')
    items = [{'name': n, 'title': engine.checks_module.TITLES[n], 'result': r, 'controls': used_by.get(n, [])}
             for n, r in sorted(results.items(), key=lambda kv: ({'fail': 0, 'partial': 1, 'unknown': 2, 'pass': 3}[kv[1].status], kv[0]))]
    counts = {s: sum(1 for i in items if i['result'].status == s) for s in ('pass', 'partial', 'fail', 'unknown')}
    return render(request, 'securitycenter/posture.html', {**_nav('posture'), 'items': items, 'counts': counts})


# ------------------------------------------------------------------------------------------------ IA
@staff_required
def ai_governance(request):
    week = timezone.now() - timedelta(days=7)
    logs = AIActionLog.objects.filter(created_at__gte=week)
    policies = AIGovernancePolicy.objects.select_related('organization').order_by('organization__name')
    ctx = {
        **_nav('ai'), 'switch': GlobalAISwitch.get(),
        'policies': policies,
        'summary': {
            'requests': logs.filter(blocked=False).count(), 'blocked': logs.filter(blocked=True).count(),
            'failed': logs.filter(blocked=False, success=False).count(),
            'by_provider': logs.filter(blocked=False).values('provider').annotate(n=Count('id')).order_by('-n'),
            'by_reason': logs.filter(blocked=True).values('block_reason').annotate(n=Count('id')).order_by('-n'),
            'by_kind': logs.filter(blocked=False).values('kind').annotate(n=Count('id')).order_by('-n'),
        },
        'pending_reviews': ExecutionLog.objects.filter(status='PENDING_REVIEW').select_related('workflow__organization')[:30],
        'drafts': Workflow.objects.filter(ai_generated=True, approved_at__isnull=True).select_related('organization')[:30],
        'recent': AIActionLog.objects.all()[:25],
    }
    return render(request, 'securitycenter/ai.html', ctx)


@staff_required
@require_POST
def ai_switch(request):
    enabled = request.POST.get('enabled') == '1'
    reason = request.POST.get('reason', '').strip()
    if not enabled and not reason:
        messages.error(request, 'Informe o motivo para desligar a IA da plataforma.')
        return redirect('sc-ai')
    set_global_switch(enabled, reason=reason, changed_by=str(request.user.pk))
    messages.success(request, 'IA da plataforma LIGADA.' if enabled else 'IA da plataforma DESLIGADA (kill switch).')
    return redirect('sc-ai')


# ------------------------------------------------------------------------------------------------ privacidade / RoPA
@staff_required
def privacy_ops(request):
    open_requests = [(r, r.overdue, (r.due_at - timezone.now()).days) for r in
                     DataSubjectRequest.objects.filter(status__in=['open', 'in_progress']).order_by('due_at')]
    ctx = {
        **_nav('privacy'),
        'dsr': open_requests,
        'dsr_done': DataSubjectRequest.objects.filter(status__in=['fulfilled', 'rejected']).order_by('-fulfilled_at')[:10],
        'docs': LegalDocument.objects.filter(is_current=True).order_by('kind'),
        'consents': ConsentRecord.objects.values('document__kind', 'document__version', 'granted').annotate(n=Count('id')),
        'subprocessors': SubprocessorEntry.objects.filter(active=True),
        'offboarding': OrganizationOffboarding.objects.filter(status='pending'),
        'retention': {'email_body': settings.RETENTION_EMAIL_BODY_DAYS, 'payload': settings.RETENTION_EXECUTION_PAYLOAD_DAYS,
                      'integration': settings.RETENTION_INTEGRATION_LOG_DAYS, 'audit': settings.AUDIT_RETENTION_DAYS},
        'dpo_email': settings.PRIVACY_CONTACT_EMAIL,
    }
    return render(request, 'securitycenter/privacy.html', ctx)


@staff_required
def ropa(request):
    if request.GET.get('format') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="ropa.csv"'
        writer = csv.writer(response)
        keys = ['id', 'name', 'role', 'purpose', 'legal_basis', 'data_subjects', 'data_categories', 'sources', 'recipients',
                'international_transfer', 'retention', 'security']
        writer.writerow(keys)
        for p in PROCESSING_ACTIVITIES:
            writer.writerow([_csv_safe('; '.join(p[k]) if isinstance(p[k], list) else p[k]) for k in keys])
        audit.log('data.export', changes={'scope': 'ropa', 'format': 'csv'})
        return response
    return render(request, 'securitycenter/ropa.html', {**_nav('ropa'), 'activities': PROCESSING_ACTIVITIES})
