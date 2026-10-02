"""Política de retenção (LGPD art. 15-16): expurgo periódico de conteúdo que já cumpriu a finalidade."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from audit import service as audit
from audit.retention import purge_old_events
from privacy.dsr import purge_organization
from privacy.models import OrganizationOffboarding

DEFAULTS = {
    'RETENTION_EMAIL_BODY_DAYS': 90,         # corpo dos e-mails processados
    'RETENTION_EXECUTION_PAYLOAD_DAYS': 90,  # payload/resultado das execuções (mantém métricas de ROI)
    'RETENTION_INTEGRATION_LOG_DAYS': 30,    # request/response de chamadas a terceiros
}


def _days(name: str) -> int:
    return getattr(settings, name, DEFAULTS[name])


def enforce_retention(now=None) -> dict:
    """Executa todos os expurgos e devolve as contagens (também gravadas na trilha)."""
    from emails.models import EmailMessage
    from integrations.models import IntegrationLog
    from tasks.models import IntegrationLog as LegacyIntegrationLog
    from workflows.models import ExecutionLog

    now = now or timezone.now()
    ago = lambda name: now - timedelta(days=_days(name))  # noqa: E731

    result = {
        # Só e-mails já despachados: o conteúdo ainda não processado não pode ser descartado.
        'email_bodies': EmailMessage.objects.filter(is_dispatched=True, created_at__lt=ago('RETENTION_EMAIL_BODY_DAYS'))
        .exclude(body_text='').update(body_text=''),
        'execution_payloads': ExecutionLog.objects.filter(created_at__lt=ago('RETENTION_EXECUTION_PAYLOAD_DAYS'))
        .exclude(trigger_payload__isnull=True, final_result__isnull=True).update(trigger_payload=None, final_result=None),
        'integration_logs': IntegrationLog.objects.filter(attempted_at__lt=ago('RETENTION_INTEGRATION_LOG_DAYS'))
        .exclude(request_data__isnull=True, response_body__isnull=True).update(request_data=None, response_body=None),
        'legacy_integration_logs': LegacyIntegrationLog.objects.filter(attempted_at__lt=ago('RETENTION_INTEGRATION_LOG_DAYS'))
        .exclude(request_data__isnull=True, response_body__isnull=True).update(request_data=None, response_body=None),
    }

    purged_orgs = 0
    for off in OrganizationOffboarding.objects.filter(status=OrganizationOffboarding.Status.PENDING, purge_after__lte=now):
        purge_organization(off)
        purged_orgs += 1
    result['organizations_purged'] = purged_orgs
    result['audit_events'] = purge_old_events()

    audit.log('retention.purged', actor_type='system', changes=result, legal_basis='obrigacao_legal')
    return result
