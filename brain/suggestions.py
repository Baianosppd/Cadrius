"""Fase E (CAD-174): a IA observa o escritório e sugere automações.

Cada detector olha um padrão nos dados do PRÓPRIO escritório (sem modelo de terceiros) e, se a regra correspondente ainda não
existe ligada, propõe um modelo pronto ou uma regra montada (tarefa recorrente). Aceitar cria a regra DESLIGADA — o escritório
revisa, simula e liga, como qualquer regra. Dispensar não volta a sugerir por 60 dias e conta como sinal negativo.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from brain.models import AIFeedback, AutomationSuggestion

WINDOW_DAYS = 30
RECURRING_WINDOW_DAYS = 70
SNOOZE_DAYS = 60
S = AutomationSuggestion.Status


def _has_rule(org, trigger, action=None) -> bool:
    from automations.models import Rule
    for r in Rule.objects.filter(organization=org, trigger=trigger, enabled=True):
        if action is None or any(a.get('type') == action for a in r.actions or []):
            return True
    return False


def _member_tasks(org):
    from tasks.models import UserTask
    return UserTask.objects.filter(responsavel__memberships__organization=org, responsavel__memberships__is_active=True).distinct()


# ----------------------------------------------------------------------------- detectores
def _publicacoes_fatais(org, since):
    from publications.models import Publication
    n = Publication.objects.filter(organization=org, status=Publication.Status.CONFIRMED, reviewed_at__gte=since).count()
    fatal = sum(1 for p in Publication.objects.filter(organization=org, status=Publication.Status.CONFIRMED, reviewed_at__gte=since)
                .only('triage')[:300] if (p.triage or {}).get('fatal'))
    if fatal >= 3 and not _has_rule(org, 'publication_new'):
        return [('template:publicacao_prazo_fatal', 'Preparar a peça antes dos prazos fatais das publicações',
                 f'Nos últimos {WINDOW_DAYS} dias o escritório confirmou {n} publicações, {fatal} com prazo possivelmente fatal. '
                 'Esta regra cria a tarefa de preparar a peça 2 dias úteis antes do vencimento e avisa a equipe.', fatal,
                 {'template': 'publicacao_prazo_fatal'})]
    return []


def _andamentos(org, since):
    from research.models import CaseMovement, MonitoredCase
    moves = CaseMovement.objects.filter(case__organization=org, created_at__gte=since, notified=True).count()
    out = []
    if moves >= 5 and not _has_rule(org, 'case_movement', 'create_task'):
        out.append(('template:andamento_cria_tarefa', 'Tarefa para analisar cada andamento novo',
                    f'Chegaram {moves} andamentos novos nos processos acompanhados nos últimos {WINDOW_DAYS} dias. '
                    'Esta regra cria uma tarefa para o responsável analisar cada um em até 2 dias úteis.', moves,
                    {'template': 'andamento_cria_tarefa'}))
    with_consent = sum(1 for c in MonitoredCase.objects.filter(organization=org, client__isnull=False).select_related('client')
                       if c.client.can_receive('whatsapp'))
    if moves >= 3 and with_consent and not _has_rule(org, 'case_movement', 'send_whatsapp'):
        out.append(('template:andamento_avisa_cliente', 'Avisar o cliente por WhatsApp a cada andamento',
                    f'{with_consent} processo(s) têm cliente que autorizou WhatsApp e houve {moves} andamentos no período. '
                    'A mensagem só sai depois que alguém da equipe aprova o texto.', moves, {'template': 'andamento_avisa_cliente'}))
    return out


def _prazos_pendentes(org, since):
    pending = _member_tasks(org).filter(completed=False, titulo__istartswith='Prazo', scheduled_at__gte=timezone.now()).count()
    if pending >= 5 and not _has_rule(org, 'deadline_soon'):
        return [('template:prazo_lembrete', 'Lembrete de prazo 3 dias úteis antes',
                 f'Há {pending} tarefas de prazo em aberto na agenda. Esta regra avisa a equipe quando cada uma estiver a 3 dias úteis.',
                 pending, {'template': 'prazo_lembrete'})]
    return []


def _documentos_fatais(org, since):
    from documents.models import DocumentExtraction
    qs = DocumentExtraction.objects.filter(document__organization=org, status=DocumentExtraction.Status.CONFIRMED, reviewed_at__gte=since)
    fatal = sum(1 for ex in qs.only('fields')[:300] if any((p or {}).get('fatal') for p in (ex.fields or {}).get('prazos') or []))
    if fatal >= 3 and not _has_rule(org, 'document_confirmed'):
        return [('template:documento_prazo_fatal', 'Revisão da peça no dia útil anterior ao prazo fatal',
                 f'{fatal} documentos confirmados nos últimos {WINDOW_DAYS} dias tinham prazo fatal. '
                 'Esta regra agenda a revisão 1 dia útil antes e avisa a equipe.', fatal, {'template': 'documento_prazo_fatal'})]
    return []


def _boas_vindas(org, since):
    from contacts.models import Contact
    qs = Contact.objects.filter(organization=org, kind=Contact.Kind.CLIENT, source=Contact.Source.MANUAL, created_at__gte=since)
    n = qs.count()
    consent = sum(1 for c in qs[:200] if c.can_receive('email'))
    if n >= 3 and consent and not _has_rule(org, 'contact_created'):
        return [('template:cliente_boas_vindas', 'E-mail de boas-vindas a cada cliente novo',
                 f'{n} clientes foram cadastrados nos últimos {WINDOW_DAYS} dias ({consent} autorizaram e-mail). '
                 'A regra envia as boas-vindas depois da aprovação de alguém da equipe.', n, {'template': 'cliente_boas_vindas'})]
    return []


_DATE_RX = re.compile(r'\d{1,2}[/.-]\d{1,2}([/.-]\d{2,4})?|\d+')
WEEKDAYS = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']


def normalize_title(title: str) -> str:
    """'Relatório semanal 12/03 - Cliente X' → 'relatorio semanal cliente x' (sem datas/números/acentos, 6 palavras)."""
    t = unicodedata.normalize('NFKD', (title or '').lower())
    t = ''.join(ch for ch in t if not unicodedata.combining(ch))
    t = _DATE_RX.sub(' ', t)
    words = re.findall(r'[a-z]{2,}', t)
    return ' '.join(words[:6])


def _tarefas_recorrentes(org, since):
    """Tarefas criadas à mão com o mesmo assunto em semanas diferentes, quase sempre no mesmo dia → regra semanal."""
    since = timezone.now() - timedelta(days=RECURRING_WINDOW_DAYS)
    groups = defaultdict(list)
    for t in _member_tasks(org).filter(created_at__gte=since).only('titulo', 'scheduled_at', 'priority')[:2000]:
        key = normalize_title(t.titulo)
        if len(key) >= 6 and not key.startswith('prazo') and not key.startswith('analisar andamento'):
            groups[key].append(t)
    out = []
    for key, items in groups.items():
        days = [timezone.localtime(t.scheduled_at) for t in items]
        weeks = {(d.isocalendar()[0], d.isocalendar()[1]) for d in days}
        if len(items) < 4 or len(weeks) < 3:
            continue
        weekday, hits = Counter(d.weekday() for d in days).most_common(1)[0]
        if hits / len(days) < 0.6:
            continue
        hour = Counter(d.hour for d in days).most_common(1)[0][0]
        title = items[-1].titulo[:120]
        rule = {'name': f'Toda {WEEKDAYS[weekday]}: {title}'[:120], 'trigger': 'schedule',
                'trigger_config': {'frequencia': 'semanal', 'dia_semana': weekday, 'hora': max(6, min(hour, 20)), 'so_dias_uteis': True},
                'conditions': [], 'actions': [{'type': 'create_task', 'params': {'titulo': title, 'descricao': 'Criada pela regra semanal.',
                                                                                    'prioridade': items[-1].priority or 'media',
                                                                                    'quando': 'dias_uteis', 'dias': 0}}]}
        out.append((f'recorrente:{key}'[:80], f'Criar "{title}" toda {WEEKDAYS[weekday]}',
                    f'Esta tarefa foi criada à mão {len(items)} vezes em {len(weeks)} semanas, quase sempre na {WEEKDAYS[weekday]}. '
                    'A regra cria a tarefa sozinha toda semana (em dias úteis).', len(items), {'rule': rule}))
    return out


DETECTORS = [_publicacoes_fatais, _andamentos, _prazos_pendentes, _documentos_fatais, _boas_vindas, _tarefas_recorrentes]


def detect(org) -> list:
    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    found = []
    for fn in DETECTORS:
        try:
            found.extend(fn(org, since))
        except Exception:  # noqa: BLE001 — um detector com problema não impede os outros
            import logging
            logging.getLogger(__name__).exception('Detector %s falhou (org %s)', fn.__name__, org.pk)
    return found


def refresh(org, notify=True) -> list:
    """Recalcula as sugestões abertas do escritório. Devolve as NOVAS."""
    now = timezone.now()
    found = detect(org)
    keys = {f[0] for f in found}
    created = []
    with transaction.atomic():
        (AutomationSuggestion.objects.filter(organization=org, status=S.OPEN).exclude(key__in=keys)
         .exclude(key__startswith='entrevista:').delete())   # as da entrevista (CAD-226) não vêm dos detectores   # o padrão sumiu ou já há regra
        for key, title, reason, evidence, payload in found:
            s = AutomationSuggestion.objects.filter(organization=org, key=key).first()
            if s is None:
                created.append(AutomationSuggestion.objects.create(organization=org, key=key, title=title, reason=reason,
                                                                   evidence=evidence, payload=payload))
            elif s.status == S.OPEN:
                s.title, s.reason, s.evidence, s.payload = title, reason, evidence, payload
                s.save()
            elif s.status == S.DISMISSED and s.decided_at and s.decided_at < now - timedelta(days=SNOOZE_DAYS):
                s.title, s.reason, s.evidence, s.payload, s.status, s.decided_at, s.decided_by = title, reason, evidence, payload, S.OPEN, None, None
                s.save()
                created.append(s)
    if created and notify:
        from notifications.models import Notification
        from notifications.services import AUTOMACOES_LINK, notify as send
        send(type=Notification.Type.AUTOMACAO, title='A IA sugeriu automações para o escritório', organization=org,
             description=f'{len(created)} sugestão(ões) com base no que a equipe tem feito. Revise antes de ligar.',
             origem='IA do escritório', acao='Sugestão de automação', action_label='Ver sugestões',
             link=f'{AUTOMACOES_LINK}?aba=regras', dedupe_key=f'sugestoes-{org.pk}-{now:%Y%m%d}')
    return created


class SuggestionError(ValueError):
    pass


def accept(suggestion: AutomationSuggestion, user):
    from audit import service as audit
    from automations import catalog
    from automations.models import Rule
    from automations.templates import TEMPLATES

    if suggestion.status != S.OPEN:
        raise SuggestionError('Esta sugestão já foi decidida.')
    payload = suggestion.payload or {}
    if payload.get('template') in TEMPLATES:
        data, key = TEMPLATES[payload['template']], payload['template']
    elif isinstance(payload.get('rule'), dict):
        data, key = payload['rule'], ''
    else:
        raise SuggestionError('Sugestão sem regra válida.')
    try:
        clean = catalog.clean_rule(data)
    except catalog.RuleError as exc:
        raise SuggestionError(str(exc)) from exc
    with transaction.atomic():
        rule = Rule.objects.create(organization=suggestion.organization, created_by=user, template_key=key, enabled=False,
                                   description=f'Sugerida pela IA: {suggestion.title}'[:500], **clean)
        suggestion.status, suggestion.rule, suggestion.decided_by, suggestion.decided_at = S.ACCEPTED, rule, user, timezone.now()
        suggestion.save()
    _signal(suggestion, user, AIFeedback.Decision.APPROVED)
    audit.log('automation.suggestion_decided', actor=user, organization=suggestion.organization, target=rule,
              changes={'sugestao': suggestion.key, 'decisao': 'aceita'})
    return rule


def dismiss(suggestion: AutomationSuggestion, user):
    from audit import service as audit

    if suggestion.status != S.OPEN:
        raise SuggestionError('Esta sugestão já foi decidida.')
    suggestion.status, suggestion.decided_by, suggestion.decided_at = S.DISMISSED, user, timezone.now()
    suggestion.save()
    _signal(suggestion, user, AIFeedback.Decision.REJECTED)
    audit.log('automation.suggestion_decided', actor=user, organization=suggestion.organization, target_type='suggestion',
              target_id=str(suggestion.pk), changes={'sugestao': suggestion.key, 'decisao': 'dispensada'})
    return suggestion


def _signal(suggestion, user, decision):
    from brain import feedback
    feedback.record_decision(suggestion.organization, user, 'automation_suggestion', f'suggestion:{suggestion.key}'[:60], decision)
