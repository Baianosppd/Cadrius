"""Sincronização Tarefa (UserTask) ↔ evento do Google Calendar (CAD-162).

* **Push** (Cadrius → Google): ao criar/editar/concluir/excluir uma tarefa com ``sincronizar=True`` (fila Django-Q, com retentativa).
* **Pull** (Google → Cadrius): a cada 15 min (``gcal_pull``), por ``syncToken`` incremental. Mudar horário/título no Google atualiza a tarefa;
  apagar o evento no Google desliga a sincronização da tarefa (ela continua no Cadrius).
* **Conflito:** vale a alteração mais recente; ecos das nossas próprias gravações são ignorados (``TaskEventMap.last_synced_at``).
* **Privacidade:** com ``share_details=False`` o evento leva só "Tarefa Cadrius".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_tz

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from audit import service as audit
from gcal import google_api as g
from gcal.models import GoogleCalendarLink, TaskEventMap

logger = logging.getLogger(__name__)
PRIORITY_COLOR = {'alta': '11', 'media': '5', 'baixa': '2'}   # vermelho / amarelo / verde
DONE_PREFIX = '✔ '
GENERIC_TITLE = 'Tarefa Cadrius'


# ----------------------------------------------------------------------------- tokens
def _access_token(link: GoogleCalendarLink) -> str:
    key = f'gcal:at:{link.pk}'
    token = cache.get(key)
    if token:
        return token
    token, ttl = g.refresh_access_token(link.app.client_id, link.app.client_secret, link.refresh_token)
    cache.set(key, token, max(ttl - 120, 60))
    return token


def _mark_needs_reauth(link, reason):
    link.status = GoogleCalendarLink.Status.NEEDS_REAUTH
    link.last_error = reason[:255]
    link.save(update_fields=['status', 'last_error'])
    cache.delete(f'gcal:at:{link.pk}')
    audit.log('connection.updated', actor=link.user, reason=f'google_calendar: precisa reconectar ({reason[:60]})',
              changes={'provider': 'google_calendar', 'status': 'needs_reauth'})
    try:  # aviso no sininho do usuário (mesmo mecanismo das demais integrações)
        from notifications.services import notify_integration_failure
        notify_integration_failure(integration='Google Calendar', actor_id=link.user_id,
                                   organization=link.app.organization, detalhes='Reconecte em Integrações.',
                                   dedupe_key=f'gcal-reauth-{link.pk}')
    except Exception:  # noqa: BLE001 — avisar é best-effort
        logger.debug('sem aviso de reconexão', exc_info=True)


def _call(link, method, path, **kw):
    """Chamada autenticada com 1 renovação de token; invalid_grant marca a conexão para reconectar."""
    try:
        try:
            return g.calendar_call(_access_token(link), method, path, **kw)
        except g.GoogleAuthError:
            cache.delete(f'gcal:at:{link.pk}')           # access token vencido: renova uma vez
            return g.calendar_call(_access_token(link), method, path, **kw)
    except g.GoogleAuthError as exc:
        _mark_needs_reauth(link, str(exc))
        raise


# ----------------------------------------------------------------------------- conversões
def event_body(task, app) -> dict:
    title = task.titulo if app.share_details else GENERIC_TITLE
    if task.completed:
        title = DONE_PREFIX + title
    start = task.scheduled_at
    end = start + timedelta(minutes=app.event_minutes)
    body = {
        'summary': title,
        'start': {'dateTime': start.isoformat(), 'timeZone': settings.TIME_ZONE},
        'end': {'dateTime': end.isoformat(), 'timeZone': settings.TIME_ZONE},
        'colorId': PRIORITY_COLOR.get(task.priority, '5'),
        'transparency': 'transparent' if task.completed else 'opaque',
        'extendedProperties': {'private': {'cadrius_task_id': str(task.pk), 'cadrius': '1'}},
        'reminders': {'useDefault': True},
    }
    if app.share_details and task.descricao:
        body['description'] = task.descricao
    return body


def _parse_dt(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=dt_tz.utc)


# ----------------------------------------------------------------------------- push
def _link_for(user):
    link = getattr(user, 'gcal_link', None) if user else None
    return link if link and link.status == GoogleCalendarLink.Status.ACTIVE and link.app.enabled else None


def push_task(task_pk):
    """Cria/atualiza/remove o evento da tarefa. Tarefa sem sincronização (ou sem conexão ativa) remove o evento que existir."""
    from tasks.models import UserTask
    task = UserTask.objects.select_related('responsavel').filter(pk=task_pk).first()
    if task is None:
        return 'gone'
    mapping = TaskEventMap.objects.select_related('link__app', 'link__user').filter(task=task).first()
    link = _link_for(task.responsavel)

    if not task.sincronizar or link is None:
        if mapping is not None:
            _delete_event(mapping.link, mapping.event_id)
            mapping.delete()
            return 'removed'
        return 'noop'

    body = event_body(task, link.app)
    now = timezone.now()
    try:
        if mapping is not None and mapping.link_id == link.pk:
            try:
                _call(link, 'PATCH', f'/calendars/{link.calendar_id}/events/{mapping.event_id}', json=body)
                mapping.last_synced_at = now
                mapping.save(update_fields=['last_synced_at'])
                return 'updated'
            except g.GoogleNotFound:
                mapping.delete()                                 # apagado no Google: recria abaixo
        event = _call(link, 'POST', f'/calendars/{link.calendar_id}/events', json=body)
        TaskEventMap.objects.update_or_create(task=task, defaults={'link': link, 'event_id': event['id'], 'last_synced_at': now})
        return 'created'
    except g.GoogleAuthError:
        return 'needs_reauth'


def _delete_event(link, event_id):
    try:
        _call(link, 'DELETE', f'/calendars/{link.calendar_id}/events/{event_id}')
    except g.GoogleNotFound:
        pass
    except g.GoogleAuthError:
        logger.info('Não foi possível remover o evento %s: conexão precisa ser refeita', event_id)


def delete_event(link_pk, event_id):
    """Chamado quando a tarefa foi excluída (o mapeamento some junto com ela, por isso recebe os dados)."""
    link = GoogleCalendarLink.objects.select_related('app', 'user').filter(pk=link_pk).first()
    if link and link.status == GoogleCalendarLink.Status.ACTIVE:
        _delete_event(link, event_id)


# ----------------------------------------------------------------------------- pull
def pull_link(link: GoogleCalendarLink) -> dict:
    from tasks.models import UserTask
    stats = {'updated': 0, 'unsynced': 0}
    params = {'privateExtendedProperty': 'cadrius=1', 'showDeleted': 'true', 'singleEvents': 'true', 'maxResults': 250}
    if link.sync_token:
        params['syncToken'] = link.sync_token
    else:
        params['timeMin'] = (timezone.now() - timedelta(days=7)).isoformat()
    page_token, next_sync = None, None
    try:
        while True:
            if page_token:
                params['pageToken'] = page_token
            try:
                data = _call(link, 'GET', f'/calendars/{link.calendar_id}/events', params=params)
            except g.GoogleNotFound:                              # syncToken inválido (410): recomeça do zero
                link.sync_token = ''
                link.save(update_fields=['sync_token'])
                return pull_link(link) if 'syncToken' in params else stats
            for ev in data.get('items', []):
                task_id = ((ev.get('extendedProperties') or {}).get('private') or {}).get('cadrius_task_id')
                mapping = TaskEventMap.objects.select_related('task').filter(link=link, event_id=ev.get('id')).first()
                if mapping is None or str(mapping.task_id) != str(task_id):
                    continue
                task = mapping.task
                if ev.get('status') == 'cancelled':               # apagado no Google: a tarefa fica, sem sincronizar
                    UserTask.objects.filter(pk=task.pk).update(sincronizar=False)
                    mapping.delete()
                    stats['unsynced'] += 1
                    continue
                updated = _parse_dt(ev.get('updated'))
                if updated and updated <= mapping.last_synced_at:  # eco da nossa própria gravação
                    continue
                changes = {}
                start = _parse_dt((ev.get('start') or {}).get('dateTime'))
                if start and start != task.scheduled_at:
                    changes['scheduled_at'] = start
                summary = ev.get('summary') or ''
                if link.app.share_details and summary:
                    clean = summary[len(DONE_PREFIX):] if summary.startswith(DONE_PREFIX) else summary
                    if clean and clean != task.titulo:
                        changes['titulo'] = clean
                if changes:
                    UserTask.objects.filter(pk=task.pk).update(**changes)   # update() não dispara o sinal (sem laço de eco)
                    stats['updated'] += 1
                mapping.last_synced_at = timezone.now()
                mapping.save(update_fields=['last_synced_at'])
            page_token = data.get('nextPageToken')
            next_sync = data.get('nextSyncToken') or next_sync
            if not page_token:
                break
    except g.GoogleAuthError:
        return {**stats, 'error': 'needs_reauth'}
    link.sync_token = next_sync or link.sync_token
    link.last_sync_at = timezone.now()
    link.last_error = ''
    link.save(update_fields=['sync_token', 'last_sync_at', 'last_error'])
    return stats


def pull_all():
    """Agendado a cada 15 min (django-q): sincroniza todas as conexões ativas."""
    total = {'links': 0, 'updated': 0, 'unsynced': 0, 'errors': 0}
    for link in GoogleCalendarLink.objects.select_related('app', 'user').filter(status='active', app__enabled=True):
        try:
            res = pull_link(link)
        except g.GoogleRetryable:
            total['errors'] += 1
            continue
        total['links'] += 1
        total['updated'] += res.get('updated', 0)
        total['unsynced'] += res.get('unsynced', 0)
        total['errors'] += 1 if res.get('error') else 0
    return total
