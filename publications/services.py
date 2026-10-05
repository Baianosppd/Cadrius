"""Captura, triagem e confirmação das publicações (CAD-173)."""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from audit import service as audit
from core.pii import blind_index
from publications import triage as triage_mod
from publications.models import OabWatch, Publication
from publications.providers import djen
from research.providers.datajud import ProviderError

logger = logging.getLogger(__name__)

FIRST_WINDOW_DAYS = 7      # 1ª consulta de uma OAB: última semana
WINDOW_DAYS = 3            # demais: últimos 3 dias (o DJEN pode publicar com atraso; o id evita duplicar)


class ReviewError(ValueError):
    pass


def _calendar(org, tribunal):
    from forense.calendar import Calendar
    return Calendar(org, (tribunal or '').lower())


def compute_dates(pub, prazo_dias):
    """(publicação, vencimento) pela regra do DJe: publicação = 1º dia útil após a disponibilização; prazo conta dali."""
    cal = _calendar(pub.organization, pub.tribunal)
    if not prazo_dias:
        return cal.next_business_day(pub.disponibilizada_em + timedelta(days=1), []), None
    r = cal.count(pub.disponibilizada_em, int(prazo_dias), from_availability=True)
    return r['publicacao'], r['vencimento']


def _link_case(pub):
    from research.models import MonitoredCase

    if not pub.cnj:
        return None
    bidx = blind_index('case.cnj', pub.cnj, 'digits')
    return MonitoredCase.objects.filter(organization=pub.organization, cnj_bidx=bidx).first() if bidx else None


def ingest(watch: OabWatch, item: dict) -> Publication | None:
    """Grava uma comunicação nova (None se já existia) com a triagem e as datas sugeridas."""
    org = watch.organization
    if Publication.objects.filter(organization=org, external_id=item['external_id']).exists():
        return None
    pub = Publication(organization=org, watch=watch, **item)
    pub.triage = triage_mod.triage(org, pub.texto, pub.tipo)
    pub.publicada_em, pub.vencimento = compute_dates(pub, pub.triage.get('prazo_dias'))
    pub.case = _link_case(pub)
    try:
        with transaction.atomic():
            pub.save()
    except Exception:  # noqa: BLE001 — corrida com outra consulta (unique): já está na caixa
        if Publication.objects.filter(organization=org, external_id=item['external_id']).exists():
            return None
        raise
    return pub


def poll_watch(watch: OabWatch, today=None) -> dict:
    today = today or timezone.localdate()
    days = FIRST_WINDOW_DAYS if watch.last_checked_at is None else WINDOW_DAYS
    try:
        items = djen.search(watch.numero, watch.uf, today - timedelta(days=days), today)
    except ProviderError as exc:
        watch.last_error, watch.last_checked_at = str(exc)[:200], timezone.now()
        watch.save(update_fields=['last_error', 'last_checked_at'])
        return {'new': 0, 'error': str(exc)}
    created = [p for p in (ingest(watch, i) for i in items) if p]
    watch.last_error, watch.last_checked_at = '', timezone.now()
    watch.save(update_fields=['last_error', 'last_checked_at'])
    if created:
        _notify(watch, created)
        audit.log('publication.captured', actor_type='system', organization=watch.organization, target=watch,
                  changes={'source': 'djen', 'novas': len(created)}, data_categories=['dados_processuais'],
                  legal_basis='exercicio_regular_direitos')
        from automations.engine import emit
        for p in created:
            emit(watch.organization, 'publication_new', {'publication_id': p.pk}, f'publication-{p.pk}')
    return {'new': len(created), 'error': ''}


def _notify(watch, created):
    from notifications.models import Notification
    from notifications.services import notify

    fatal = sum(1 for p in created if p.triage.get('fatal'))
    notify(type=Notification.Type.PRAZO, title=f'{len(created)} publicação(ões) nova(s) no DJEN', organization=watch.organization,
           actor_id=watch.responsavel_id, origem='Caixa de publicações', documento=str(watch),
           description=f'{str(watch)}: {len(created)} nova(s)' + (f', {fatal} com prazo possivelmente fatal.' if fatal else '.'),
           acao='Triar publicações', action_label='Abrir a caixa', link='/publicacoes',
           dedupe_key=f'djen-{watch.pk}-{created[0].pk}')


def poll_all() -> dict:
    total = {'oabs': 0, 'new': 0, 'errors': 0}
    for watch in OabWatch.objects.filter(is_active=True, organization__is_active=True).select_related('organization'):
        res = poll_watch(watch)
        total['oabs'] += 1
        total['new'] += res['new']
        total['errors'] += 1 if res['error'] else 0
    return total


# ----------------------------------------------------------------------------- revisão humana
def _member(org, user_id):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    if user is None or not user.memberships.filter(organization=org, is_active=True).exists():
        return None
    return user


def confirm(pub: Publication, user, *, prazo_dias=None, vencimento=None, responsavel_id=None, acompanhar=False, note=''):
    """Confirma a triagem: cria a tarefa do prazo (se houver), vincula/acompanha o processo e registra o aprendizado."""
    from django.utils.dateparse import parse_date

    from research.models import MonitoredCase
    from tasks.models import UserTask

    if pub.status != Publication.Status.NEW:
        raise ReviewError('Esta publicação já foi revisada.')
    original = dict(pub.triage or {})
    if prazo_dias not in (None, ''):
        try:
            prazo_dias = int(prazo_dias)
        except (TypeError, ValueError) as exc:
            raise ReviewError('Prazo em dias inválido.') from exc
        if not 1 <= prazo_dias <= 365:
            raise ReviewError('Prazo entre 1 e 365 dias úteis.')
    else:
        prazo_dias = original.get('prazo_dias')
    due = parse_date(str(vencimento)) if vencimento else None
    if vencimento and due is None:
        raise ReviewError('Vencimento no formato AAAA-MM-DD.')
    if due is None and prazo_dias:
        _, due = compute_dates(pub, prazo_dias)
    owner = _member(pub.organization, responsavel_id) or (pub.watch.responsavel if pub.watch and pub.watch.responsavel_id else None) or user
    with transaction.atomic():
        if acompanhar and pub.case is None and pub.cnj:
            from research import cnj as cnj_mod
            parsed = cnj_mod.parse(pub.cnj)
            alias = cnj_mod.tribunal_alias(parsed) if parsed else None
            if alias:
                pub.case = MonitoredCase.objects.create(organization=pub.organization, cnj=parsed['formatted'], tribunal=alias,
                                                        responsavel=owner)
        if due:
            ato = (pub.triage or {}).get('ato') or pub.tipo or 'Publicação'
            pub.task = UserTask.objects.create(
                titulo=f'Prazo: {ato} — {pub.cnj or pub.tribunal}'[:255],
                descricao=f'{(pub.triage or {}).get("providencia", "")} Disponibilizada em {pub.disponibilizada_em:%d/%m/%Y} '
                          f'({pub.tribunal}).'[:2000],
                scheduled_at=timezone.make_aware(datetime.combine(due, time(9, 0))),
                priority='alta' if (pub.triage or {}).get('fatal') else 'media', responsavel=owner)
        pub.triage = {**original, 'prazo_dias': prazo_dias}
        pub.vencimento = due
        pub.status, pub.reviewed_by, pub.reviewed_at, pub.review_note = Publication.Status.CONFIRMED, user, timezone.now(), note[:255]
        pub.save()
    _learn(pub, user, original)
    audit.log('publication.reviewed', actor=user, organization=pub.organization, target=pub,
              changes={'decision': 'confirmada', 'prazo_dias': prazo_dias, 'tarefa': bool(pub.task_id),
                       'ajustou_prazo': prazo_dias != original.get('prazo_dias')}, data_categories=['dados_processuais'])
    return pub


def _learn(pub, user, original):
    try:
        from brain import feedback
        keys = ('ato', 'prazo_dias', 'fatal')
        feedback.record_review(pub.organization, user, 'deadline_task', f'publication:{pub.pk}',
                               {k: original.get(k) for k in keys}, {k: pub.triage.get(k) for k in keys}, original.get('confianca'))
    except Exception:  # noqa: BLE001 — aprender nunca impede a confirmação
        logger.exception('Falha ao registrar o aprendizado da publicação %s', pub.pk)


def discard(pub: Publication, user, note=''):
    if pub.status != Publication.Status.NEW:
        raise ReviewError('Esta publicação já foi revisada.')
    pub.status, pub.reviewed_by, pub.reviewed_at, pub.review_note = Publication.Status.DISCARDED, user, timezone.now(), (note or '')[:255]
    pub.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])
    audit.log('publication.reviewed', actor=user, organization=pub.organization, target=pub, changes={'decision': 'descartada'},
              reason=(note or '')[:255])
    return pub


def reopen(pub: Publication, user):
    """Volta para "nova". A tarefa criada na confirmação é mantida (apague-a na agenda, se for o caso)."""
    if pub.status == Publication.Status.NEW:
        raise ReviewError('A publicação já está aberta.')
    pub.status, pub.reviewed_by, pub.reviewed_at = Publication.Status.NEW, None, None
    pub.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
    audit.log('publication.reviewed', actor=user, organization=pub.organization, target=pub, changes={'decision': 'reaberta'})
    return pub
