"""Compromissos criados direto no Google Agenda → Cadrius (CAD-222).

A cada 15 min (junto com o ``gcal_pull``) traz os eventos dos próximos N dias que NÃO foram criados pelo Cadrius:
- classifica (prazo, audiência, perícia, reunião, outro) pelo título/descrição (a pessoa pode corrigir; a correção vale);
- liga ao processo (nº CNJ no texto) e ao cliente (convidado com e-mail cadastrado, ou cliente do processo);
- cria a tarefa no Cadrius para os tipos escolhidos (padrão: prazo e audiência) — assim entram no "Prazo chegando";
- vira o gatilho "Compromisso da Agenda Google chegando" (avisar cliente por WhatsApp/e-mail, equipe, Slack…).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, time, timedelta

from django.utils import timezone

from gcal.models import ExternalEvent, GoogleCalendarLink

logger = logging.getLogger(__name__)
CNJ_RE = re.compile(r'\b(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})\b')
KINDS = [  # ordem importa: o 1º que bater vence
    ('audiencia', ('audiencia', 'conciliacao', 'instrucao e julgamento', 'sessao de julgamento', 'sustentacao oral')),
    ('pericia', ('pericia', 'diligencia', 'vistoria', 'oitiva')),
    ('prazo', ('prazo', 'vence', 'vencimento', 'protocolar', 'protocolo', 'contestacao', 'recurso', 'apelacao', 'replica',
               'manifestacao', 'embargos', 'contrarrazoes', 'agravo', 'memoriais')),
    ('reuniao', ('reuniao', 'atendimento', 'consulta', 'call', 'meet', 'videochamada', 'cliente')),
]
TASK_PREFIX = {'prazo': 'Prazo', 'audiencia': 'Audiência', 'pericia': 'Perícia', 'reuniao': 'Reunião', 'outro': 'Compromisso'}
SYNC_EVERY = timedelta(minutes=14)


def _norm(text: str) -> str:
    return unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().lower()


def classify(title: str, description: str = '') -> str:
    hay = _norm(f'{title}\n{description[:2000]}')
    for kind, words in KINDS:
        if any(w in hay for w in words):
            return kind
    return 'outro'


def _case_for(org, text):
    from core.pii import blind_index
    from research.models import MonitoredCase
    m = CNJ_RE.search(text or '')
    if not m:
        return None
    return MonitoredCase.objects.filter(organization=org, cnj_bidx=blind_index('case.cnj', ''.join(m.groups()), 'digits')).first()


def _contact_for(org, attendees, own_email):
    from contacts.models import Contact
    from core.pii import blind_index
    for a in attendees or []:
        email = (a.get('email') or '').lower()
        if not email or email == (own_email or '').lower() or a.get('self'):
            continue
        c = Contact.objects.filter(organization=org, email_bidx=blind_index('contact.email', email, 'text')).first()
        if c:
            return c
    return None


def _start(ev):
    from gcal.sync import _parse_dt
    s = ev.get('start') or {}
    if s.get('dateTime'):
        return _parse_dt(s['dateTime']), False
    if s.get('date'):
        day = datetime.fromisoformat(s['date']).date()
        return timezone.make_aware(datetime.combine(day, time(9, 0))), True
    return None, False


def _ensure_task(link, obj):
    from tasks.models import UserTask
    if obj.task_id or obj.kind not in (link.task_kinds or []) or obj.start < timezone.now():
        return
    task = UserTask.objects.create(titulo=f'{TASK_PREFIX[obj.kind]}: {obj.title}'[:255],
                                   descricao='Trazido do Google Agenda.' + (f'\nLocal: {obj.location}' if obj.location else ''),
                                   scheduled_at=obj.start, priority='alta' if obj.kind in ('prazo', 'audiencia') else 'media',
                                   responsavel=link.user, sincronizar=False)       # não volta para o Google (evita duplicar)
    obj.task = task
    obj.save(update_fields=['task'])


def pull_external(link: GoogleCalendarLink, *, force=False) -> dict:
    from accounts.team_roles import get_active_membership
    from gcal import sync

    stats = {'new': 0, 'updated': 0, 'cancelled': 0, 'tasks': 0}
    if not link.import_events:
        return stats
    if not force and link.events_synced_at and timezone.now() - link.events_synced_at < SYNC_EVERY:
        return stats
    membership = get_active_membership(link.user)
    if membership is None:
        return stats
    org = membership.organization
    now = timezone.now()
    window_end = now + timedelta(days=max(1, min(link.lookahead_days or 60, 180)))
    params = {'timeMin': (now - timedelta(days=1)).isoformat(), 'timeMax': window_end.isoformat(), 'singleEvents': 'true',
              'orderBy': 'startTime', 'maxResults': 250, 'showDeleted': 'true'}
    seen, page = set(), None
    while True:
        if page:
            params['pageToken'] = page
        data = sync._call(link, 'GET', f'/calendars/{link.calendar_id}/events', params=params)
        for ev in data.get('items', []):
            private = (ev.get('extendedProperties') or {}).get('private') or {}
            if private.get('cadrius') == '1':                 # criado pelo próprio Cadrius (tarefa sincronizada)
                continue
            eid = ev.get('id')
            if not eid:
                continue
            seen.add(eid)
            obj = ExternalEvent.objects.filter(link=link, event_id=eid).first()
            if ev.get('status') == 'cancelled':
                if obj and not obj.cancelled:
                    obj.cancelled = True
                    obj.save(update_fields=['cancelled'])
                    stats['cancelled'] += 1
                continue
            start, all_day = _start(ev)
            if start is None:
                continue
            end = sync._parse_dt((ev.get('end') or {}).get('dateTime')) if not all_day else None
            title, desc = (ev.get('summary') or '(sem título)')[:500], (ev.get('description') or '')[:4000]
            fields = {'title': title, 'description': desc, 'location': (ev.get('location') or '')[:300], 'start': start, 'end': end,
                      'all_day': all_day, 'cancelled': False}
            if obj is None:
                case = _case_for(org, f'{title} {desc}')
                obj = ExternalEvent.objects.create(link=link, organization=org, event_id=eid, kind=classify(title, desc), case=case,
                                                   contact=_contact_for(org, ev.get('attendees'), link.user.email)
                                                   or (case.client if case else None), **fields)
                stats['new'] += 1
            else:
                changed = [k for k, v in fields.items() if getattr(obj, k) != v]
                if changed:
                    for k in changed:
                        setattr(obj, k, fields[k])
                    if not obj.kind_locked and {'title', 'description'} & set(changed):
                        obj.kind = classify(title, desc)
                        changed.append('kind')
                    obj.save(update_fields=changed)
                    stats['updated'] += 1
                    if obj.task_id and 'start' in changed:
                        from tasks.models import UserTask
                        UserTask.objects.filter(pk=obj.task_id).update(scheduled_at=obj.start)
            had_task = obj.task_id
            _ensure_task(link, obj)
            stats['tasks'] += 1 if obj.task_id and not had_task else 0
        page = data.get('nextPageToken')
        if not page:
            break
    gone = ExternalEvent.objects.filter(link=link, cancelled=False, start__gte=now, start__lte=window_end).exclude(event_id__in=seen)
    stats['cancelled'] += gone.update(cancelled=True)
    link.events_synced_at = timezone.now()
    link.save(update_fields=['events_synced_at'])
    return stats
