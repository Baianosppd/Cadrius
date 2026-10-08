"""Criar, alterar e cancelar compromissos direto no Google Agenda da pessoa (CAD-230).

Antes o Cadrius só gravava no Google as **tarefas** marcadas para sincronizar e só **lia** os compromissos criados lá. O
Assistente respondia "não consigo criar o evento no Google Agenda". Agora:

- o evento é criado no calendário da conexão da pessoa (escopo ``calendar.events``, o mesmo de antes: não precisa reconectar);
- vira na hora um ``ExternalEvent`` no Cadrius (aparece na agenda e no gatilho "Compromisso chegando"); a sincronização
  de 15 em 15 min continua mantendo os dois lados iguais;
- convidados só recebem e-mail do Google quando a pessoa pede (``avisar_convidados``).

Quem chama (Assistente, automação, tela) já passou pela confirmação da pessoa; aqui só se confere a conexão e o dono.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from gcal import google_api as g
from gcal.models import ExternalEvent, GoogleCalendarLink

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MAX_GUESTS = 20


class CalendarWriteError(Exception):
    """Mensagem pronta para a tela / para a IA."""


def active_link(user) -> GoogleCalendarLink:
    link = GoogleCalendarLink.objects.select_related('app', 'user').filter(user=user).first()
    if link is None:
        raise CalendarWriteError('Seu Google Agenda não está conectado. Conecte em Integrações → Google.')
    if link.status != GoogleCalendarLink.Status.ACTIVE or not link.app.enabled:
        raise CalendarWriteError('A conexão com o Google Agenda precisa ser refeita (Integrações → Google → Reconectar).')
    return link


def _iso(dt: datetime) -> dict:
    return {'dateTime': timezone.localtime(dt).isoformat(), 'timeZone': settings.TIME_ZONE}


def _guests(raw) -> list[dict]:
    emails = [str(e).strip().lower() for e in (raw or []) if str(e).strip()]
    bad = [e for e in emails if not EMAIL_RE.match(e)]
    if bad:
        raise CalendarWriteError(f'E-mail de convidado inválido: {bad[0]}')
    return [{'email': e} for e in dict.fromkeys(emails)][:MAX_GUESTS]


def _call(link, method, path, **kw):
    from gcal.sync import _call as call
    try:
        return call(link, method, path, **kw)
    except g.GoogleAuthError as exc:
        raise CalendarWriteError('O Google recusou o acesso à agenda. Reconecte em Integrações → Google.') from exc
    except g.GoogleRetryable as exc:
        raise CalendarWriteError('O Google Agenda não respondeu agora. Tente de novo em instantes.') from exc


def create_event(user, org, *, titulo: str, inicio: datetime, duracao_min: int = 60, local: str = '', descricao: str = '',
                 convidados=None, avisar_convidados: bool = False, lembrete_min: int | None = None,
                 dia_inteiro: bool = False) -> ExternalEvent:
    link = active_link(user)
    titulo = (titulo or '').strip()[:500]
    if not titulo:
        raise CalendarWriteError('Informe o título do compromisso.')
    duracao_min = max(5, min(int(duracao_min or 60), 24 * 60))
    body = {'summary': titulo, 'extendedProperties': {'private': {'cadrius_evento': '1'}}}
    if dia_inteiro:
        day = timezone.localtime(inicio).date()
        body['start'] = {'date': day.isoformat()}
        body['end'] = {'date': (day + timedelta(days=1)).isoformat()}
    else:
        body['start'] = _iso(inicio)
        body['end'] = _iso(inicio + timedelta(minutes=duracao_min))
    if local:
        body['location'] = local[:300]
    if descricao:
        body['description'] = descricao[:4000]
    guests = _guests(convidados)
    if guests:
        body['attendees'] = guests
    if lembrete_min is not None:
        body['reminders'] = {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': max(0, min(int(lembrete_min), 40320))}]}
    params = {'sendUpdates': 'all' if (guests and avisar_convidados) else 'none'}
    ev = _call(link, 'POST', f'/calendars/{link.calendar_id}/events', json=body, params=params)
    from gcal.events import classify
    start = inicio if not dia_inteiro else timezone.make_aware(datetime.combine(timezone.localtime(inicio).date(),
                                                                                 datetime.min.time().replace(hour=9)))
    obj = ExternalEvent.objects.create(
        link=link, organization=org, event_id=ev['id'], title=titulo, description=descricao[:4000], location=local[:300],
        start=start, end=None if dia_inteiro else inicio + timedelta(minutes=duracao_min), all_day=dia_inteiro,
        kind=classify(titulo, descricao))
    _audit(user, org, 'criado', obj, convidados=len(guests))
    return obj


def _own_event(user, org, event_id: int) -> ExternalEvent:
    obj = ExternalEvent.objects.select_related('link__app', 'link__user').filter(pk=event_id, organization=org,
                                                                                 link__user=user).first()
    if obj is None:
        raise CalendarWriteError('Compromisso não encontrado na sua agenda do Google.')
    if obj.cancelled:
        raise CalendarWriteError('Este compromisso já foi cancelado.')
    return obj


def update_event(user, org, event_id: int, *, titulo: str | None = None, inicio: datetime | None = None,
                 duracao_min: int | None = None, local: str | None = None, descricao: str | None = None) -> ExternalEvent:
    obj = _own_event(user, org, event_id)
    active_link(user)
    body, fields = {}, []
    if titulo is not None and titulo.strip():
        body['summary'] = obj.title = titulo.strip()[:500]
        fields.append('title')
    if local is not None:
        body['location'] = obj.location = local[:300]
        fields.append('location')
    if descricao is not None:
        body['description'] = obj.description = descricao[:4000]
        fields.append('description')
    if inicio is not None or duracao_min is not None:
        start = inicio or obj.start
        if duracao_min is None:
            duracao_min = int(((obj.end or obj.start + timedelta(hours=1)) - obj.start).total_seconds() // 60) or 60
        end = start + timedelta(minutes=max(5, min(int(duracao_min), 24 * 60)))
        body['start'], body['end'] = _iso(start), _iso(end)
        obj.start, obj.end, obj.all_day = start, end, False
        fields += ['start', 'end', 'all_day']
    if not body:
        raise CalendarWriteError('Diga o que mudar: data, hora, duração, título, local ou descrição.')
    try:
        _call(obj.link, 'PATCH', f'/calendars/{obj.link.calendar_id}/events/{obj.event_id}', json=body, params={'sendUpdates': 'none'})
    except g.GoogleNotFound as exc:
        obj.cancelled = True
        obj.save(update_fields=['cancelled'])
        raise CalendarWriteError('Este compromisso não existe mais no Google Agenda.') from exc
    obj.save(update_fields=fields)
    if obj.task_id and 'start' in fields:
        from tasks.models import UserTask
        UserTask.objects.filter(pk=obj.task_id).update(scheduled_at=obj.start)
    _audit(user, org, 'alterado', obj, campos=fields)
    return obj


def cancel_event(user, org, event_id: int) -> ExternalEvent:
    obj = _own_event(user, org, event_id)
    active_link(user)
    try:
        _call(obj.link, 'DELETE', f'/calendars/{obj.link.calendar_id}/events/{obj.event_id}', params={'sendUpdates': 'none'})
    except g.GoogleNotFound:
        pass                                               # já não existia no Google: só marca aqui
    obj.cancelled = True
    obj.save(update_fields=['cancelled'])
    _audit(user, org, 'cancelado', obj)
    return obj


def _audit(user, org, what, obj, **extra):
    from audit import service as audit
    audit.log('integration.call', actor=user, organization=org, target=obj,
              changes={'provider': 'google_calendar', 'evento': what, **extra})


def event_summary(obj: ExternalEvent) -> str:
    when = timezone.localtime(obj.start)
    hora = '' if obj.all_day else f' às {when:%H:%M}'
    return f'"{obj.title}" em {when:%d/%m/%Y}{hora}'
