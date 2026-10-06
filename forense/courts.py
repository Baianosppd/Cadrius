"""Calendário forense nacional e dados dos tribunais (CAD-223).

Equipe Cadrius (área Jurídico) cadastra suspensões e indisponibilidades a partir do ato oficial; os escritórios veem as que
afetam seus processos, a contagem de prazos já considera, e o gatilho ``court_suspension`` avisa quem tem processo no tribunal.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from django.utils import timezone

from audit import service as audit
from forense.models import CourtInfo, CourtSuspension

TRIBUNAL_RX = re.compile(r'^[a-z0-9]{2,12}$')


class CourtError(Exception):
    pass


def suspension_json(s: CourtSuspension) -> dict:
    return {'id': s.pk, 'tribunal': s.tribunal.upper() or 'Nacional', 'tribunal_sigla': s.tribunal, 'comarca': s.comarca,
            'tipo': s.kind, 'tipo_label': s.get_kind_display(), 'inicio': s.start, 'fim': s.end, 'motivo': s.reason,
            'fonte': s.source_url, 'criada_em': s.created_at}


def info_json(c: CourtInfo) -> dict:
    return {'tribunal': c.tribunal, 'sigla': c.tribunal.upper(), 'nome': c.name, 'balcao_virtual': c.balcao_virtual_url,
            'servicos': c.services_url, 'pauta': c.hearings_url, 'horario': c.hours, 'observacoes': c.notes, 'atualizado_em': c.updated_at}


def _tribunal(value) -> str:
    t = str(value or '').strip().lower()
    if t and not TRIBUNAL_RX.match(t):
        raise CourtError('Tribunal: use a sigla (ex.: tjsp, trt2, trf3) ou deixe vazio para nacional.')
    return t


def _date(value, label) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise CourtError(f'{label}: use AAAA-MM-DD.') from exc


def save_suspension(actor, data: dict, obj: CourtSuspension | None = None) -> CourtSuspension:
    tribunal = _tribunal(data.get('tribunal', obj.tribunal if obj else ''))
    kind = data.get('tipo', obj.kind if obj else CourtSuspension.Kind.DEADLINES)
    if kind not in CourtSuspension.Kind.values:
        raise CourtError('Tipo inválido.')
    start = _date(data.get('inicio', obj.start if obj else None), 'Início')
    end = _date(data.get('fim', obj.end if obj else start), 'Fim')
    if end < start or (end - start).days > 60:
        raise CourtError('O fim precisa ser no mesmo dia ou depois do início (no máximo 60 dias).')
    reason = str(data.get('motivo', obj.reason if obj else '') or '').strip()[:200]
    if len(reason) < 5:
        raise CourtError('Descreva o motivo (ex.: "Portaria 603/2026 — mudança de sistema").')
    source = str(data.get('fonte', obj.source_url if obj else '') or '').strip()[:500]
    if source and not source.startswith('https://'):
        raise CourtError('A fonte precisa ser o link oficial (https://).')
    if not source:
        raise CourtError('Informe o link do ato oficial (portaria, certidão ou aviso do tribunal).')
    fields = {'tribunal': tribunal, 'comarca': str(data.get('comarca', obj.comarca if obj else '') or '').strip()[:80], 'kind': kind,
              'start': start, 'end': end, 'reason': reason, 'source_url': source}
    created = obj is None
    if created:
        obj = CourtSuspension.objects.create(created_by=actor, **fields)
    else:
        for k, v in fields.items():
            setattr(obj, k, v)
        obj.save()
    audit.log('forense.suspension_saved', actor=actor, target=obj,
              changes={'tribunal': tribunal or 'nacional', 'inicio': start.isoformat(), 'fim': end.isoformat(), 'tipo': kind})
    if created:
        notify_offices(obj)
    return obj


def affected_orgs(s: CourtSuspension):
    from accounts.models import Organization
    qs = Organization.objects.filter(is_active=True)
    if s.tribunal:
        qs = qs.filter(monitored_cases__tribunal__iexact=s.tribunal, monitored_cases__is_active=True).distinct()
    return qs


def notify_offices(s: CourtSuspension) -> int:
    """Dispara ``court_suspension`` nos escritórios com processo no tribunal (todas, se nacional)."""
    from automations.engine import emit
    n = 0
    for org in affected_orgs(s):
        emit(org, 'court_suspension', {'suspension_id': s.pk}, f'susp-{s.pk}')
        n += 1
    return n


def for_org(org, days_back=30, days_ahead=90) -> list[dict]:
    """Suspensões recentes/próximas que afetam os tribunais dos processos do escritório (e as nacionais)."""
    from research.models import MonitoredCase
    tribunals = set(MonitoredCase.objects.filter(organization=org, is_active=True).values_list('tribunal', flat=True))
    tribunals = {t.lower() for t in tribunals if t}
    today = timezone.localdate()
    qs = CourtSuspension.objects.filter(end__gte=today - timedelta(days=days_back), start__lte=today + timedelta(days=days_ahead))
    return [suspension_json(s) for s in qs if not s.tribunal or s.tribunal in tribunals]


def save_info(actor, data: dict) -> CourtInfo:
    tribunal = _tribunal(data.get('tribunal'))
    if not tribunal:
        raise CourtError('Informe a sigla do tribunal.')
    name = str(data.get('nome') or '').strip()[:120]
    if not name:
        raise CourtError('Informe o nome do tribunal.')
    urls = {}
    for key, attr in (('balcao_virtual', 'balcao_virtual_url'), ('servicos', 'services_url'), ('pauta', 'hearings_url')):
        url = str(data.get(key) or '').strip()[:500]
        if url and not url.startswith('https://'):
            raise CourtError('Use só links oficiais com https://.')
        urls[attr] = url
    obj, _ = CourtInfo.objects.update_or_create(tribunal=tribunal, defaults={
        'name': name, 'hours': str(data.get('horario') or '').strip()[:120], 'notes': str(data.get('observacoes') or '').strip()[:500],
        'updated_by': actor, **urls})
    audit.log('forense.suspension_saved', actor=actor, target=obj, changes={'tribunal_info': tribunal})
    return obj
