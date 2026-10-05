"""Monitoramento: consulta a fonte, grava só os andamentos NOVOS e avisa o responsável. Idempotente (digest único por processo)."""
from __future__ import annotations

import logging

from django.utils import timezone

from audit import service as audit
from research.models import CaseMovement, MonitoredCase
from research.providers import datajud

logger = logging.getLogger(__name__)
FIRST_SYNC_NOTIFY_LIMIT = 0   # na 1ª consulta o histórico é gravado SEM notificar (senão vira enxurrada de avisos antigos)


def check_case(case: MonitoredCase) -> dict:
    first = case.last_checked_at is None
    try:
        data = datajud.search_case(case.cnj.replace('-', '').replace('.', ''), case.tribunal)
    except datajud.ProviderError as exc:
        case.last_error, case.last_checked_at = str(exc)[:200], timezone.now()
        case.save(update_fields=['last_error', 'last_checked_at'])
        if not exc.retryable:
            logger.warning('Monitoramento %s: %s', case.pk, exc)
        return {'new': 0, 'error': str(exc)}
    now = timezone.now()
    if data is None:
        case.last_error, case.last_checked_at = 'Processo não encontrado na fonte (pode estar em segredo de justiça ou em outro tribunal).', now
        case.save(update_fields=['last_error', 'last_checked_at'])
        return {'new': 0, 'error': case.last_error}

    created = []
    for m in data['movements']:
        _, was_new = CaseMovement.objects.get_or_create(
            case=case, digest=m['digest'],
            defaults={'occurred_at': m['occurred_at'], 'code': m['code'], 'name': m['name'], 'complement': m['complement'],
                      'notified': first})
        if was_new:
            created.append(m)
    case.last_checked_at, case.last_error = now, ''
    latest = max((m['occurred_at'] for m in data['movements'] if m['occurred_at']), default=None)
    if latest:
        case.last_movement_at = latest
    case.save(update_fields=['last_checked_at', 'last_error', 'last_movement_at'])

    if created and not first:
        _notify(case, created)
        CaseMovement.objects.filter(case=case, digest__in=[m['digest'] for m in created]).update(notified=True)
        from automations.engine import emit
        digests = sorted(m['digest'] for m in created)
        emit(case.organization, 'case_movement', {'case_id': case.pk, 'digests': digests}, f'case-{case.pk}-{digests[0][:16]}')
    if created:
        audit.log('research.movements_found', actor_type='system', organization=case.organization, target=case,
                  changes={'source': 'datajud', 'new_movements': len(created)}, data_categories=['dados_processuais'],
                  legal_basis='exercicio_regular_direitos')
    return {'new': len(created), 'error': ''}


def _notify(case, movements):
    from notifications.models import Notification
    from notifications.services import notify

    names = '; '.join(m['name'] for m in movements[:3]) + ('…' if len(movements) > 3 else '')
    notify(type=Notification.Type.PRAZO, title='Novo andamento no processo', organization=case.organization,
           actor_id=case.responsavel_id, origem='Monitoramento', documento=case.cnj,
           description=f'{case.cnj}: {names}', acao='Andamento novo', link='/processos',
           dedupe_key=f'case-{case.pk}-{movements[0]["digest"][:12]}')


def check_all() -> dict:
    total = {'cases': 0, 'new': 0, 'errors': 0}
    for case in MonitoredCase.objects.filter(is_active=True, organization__is_active=True).select_related('organization'):
        res = check_case(case)
        total['cases'] += 1
        total['new'] += res['new']
        total['errors'] += 1 if res['error'] else 0
    return total
