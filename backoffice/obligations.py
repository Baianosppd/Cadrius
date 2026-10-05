"""Setor Fiscal da Cadrius — fase 3 (CAD-175): calendário de obrigações da empresa, com marcação de "feito" e lembretes.

As obrigações-padrão (PGDAS-D/DAS, DCTFWeb, EFD-Reinf, ISS, FGTS Digital, eSocial, DEFIS) vêm de uma migração e são **editáveis**
na tela (dia, regra de dia útil, ligar/desligar): prazos mudam por norma e por município. [VALIDAR com o contador.]
Dia útil = sem fim de semana e sem feriado nacional.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit import service as audit
from backoffice.services import ActionError
from billing.models import FiscalObligation, FiscalObligationDone

DEFAULTS = [
    # code, nome, descrição, periodicidade, dia, mês (anual), ajuste
    ('pgdas-das', 'PGDAS-D e DAS (Simples Nacional)', 'Declaração e guia do mês anterior.', 'mensal', 20, 0, 'posterga'),
    ('dctfweb', 'DCTFWeb', 'Débitos previdenciários e retenções do mês anterior.', 'mensal', 0, 0, 'ultimo_util'),
    ('efd-reinf', 'EFD-Reinf', 'Retenções e informações fiscais do mês anterior.', 'mensal', 15, 0, 'antecipa'),
    ('iss', 'ISS municipal (se fora do DAS)', 'Guia do ISS conforme o município.', 'mensal', 10, 0, 'posterga'),
    ('fgts-digital', 'FGTS Digital', 'Se houver empregados.', 'mensal', 20, 0, 'antecipa'),
    ('esocial', 'eSocial (folha)', 'Eventos periódicos da folha, se houver empregados.', 'mensal', 15, 0, 'antecipa'),
    ('defis', 'DEFIS (Simples Nacional)', 'Declaração anual de informações socioeconômicas e fiscais.', 'anual', 31, 3, 'antecipa'),
]


def _closures(year):
    from forense.calendar import national_closures
    return national_closures(year)


def is_business(d: date) -> bool:
    return d.weekday() < 5 and d not in _closures(d.year)


def adjust(d: date, rule: str) -> date:
    if rule == 'ultimo_util':
        d = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        rule = 'antecipa'
    step = -1 if rule == 'antecipa' else 1
    while not is_business(d):
        d += timedelta(days=step)
    return d


def due_for(ob: FiscalObligation, competence: str) -> date:
    if ob.periodicity == 'anual':
        year = int(competence)
        month = ob.due_month or 3
        day = min(ob.due_day or 1, calendar.monthrange(year, month)[1])
        return adjust(date(year, month, day), ob.adjust)
    year, month = (int(x) for x in competence.split('-'))
    month += 1
    if month == 13:
        year, month = year + 1, 1
    day = min(ob.due_day or 1, calendar.monthrange(year, month)[1])
    return adjust(date(year, month, day), ob.adjust)


def competences_around(today: date, ob: FiscalObligation) -> list:
    if ob.periodicity == 'anual':
        return [str(today.year), str(today.year + 1)]
    out, y, m = [], today.year, today.month
    for back in range(3, -1, -1):          # 3 meses atrás até o mês corrente (vence no mês seguinte)
        mm, yy = m - back, y
        while mm <= 0:
            mm, yy = mm + 12, yy - 1
        out.append(f'{yy:04d}-{mm:02d}')
    return out


def upcoming(today=None, days=60) -> list:
    today = today or timezone.localdate()
    done = {(d.obligation_id, d.competence): d for d in FiscalObligationDone.objects.select_related('done_by')}
    rows = []
    for ob in FiscalObligation.objects.filter(active=True):
        for comp in competences_around(today, ob):
            due = due_for(ob, comp)
            d = done.get((ob.pk, comp))
            if d is None and due > today + timedelta(days=days):
                continue
            if d is not None and due < today - timedelta(days=45):
                continue
            status = 'feito' if d else ('atrasado' if due < today else ('hoje' if due == today else 'pendente'))
            rows.append({'obrigacao_id': ob.pk, 'codigo': ob.code, 'nome': ob.name, 'descricao': ob.description, 'competencia': comp,
                         'vencimento': due, 'dias': (due - today).days, 'situacao': status,
                         'feito_em': d.done_at if d else None, 'feito_por': (d.done_by.email if d and d.done_by_id else ''),
                         'obs': d.note if d else ''})
    return sorted(rows, key=lambda r: (r['situacao'] == 'feito', r['vencimento']))


def obligation_json(ob) -> dict:
    return {'id': ob.pk, 'codigo': ob.code, 'nome': ob.name, 'descricao': ob.description, 'periodicidade': ob.periodicity,
            'dia': ob.due_day, 'mes': ob.due_month, 'ajuste': ob.adjust, 'ativa': ob.active}


def update(actor, ob: FiscalObligation, data: dict, reason: str):
    if 'dia' in data:
        day = int(data['dia'])
        if not 0 <= day <= 31:
            raise ActionError('Dia entre 1 e 31 (0 = último dia útil).')
        ob.due_day = day
    if 'mes' in data and ob.periodicity == 'anual':
        month = int(data['mes'])
        if not 1 <= month <= 12:
            raise ActionError('Mês entre 1 e 12.')
        ob.due_month = month
    if 'ajuste' in data:
        if data['ajuste'] not in FiscalObligation.Adjust.values:
            raise ActionError('Regra de dia útil inválida.')
        ob.adjust = data['ajuste']
    if 'ativa' in data:
        ob.active = bool(data['ativa'])
    ob.save()
    audit.log('backoffice.action', actor=actor, reason=reason[:255], target=ob,
              changes={'action': 'fiscal_obligation_updated', **obligation_json(ob)})
    return obligation_json(ob)


def mark_done(actor, ob: FiscalObligation, competence: str, note: str = '', undo=False):
    if undo:
        FiscalObligationDone.objects.filter(obligation=ob, competence=competence).delete()
    else:
        try:
            with transaction.atomic():
                FiscalObligationDone.objects.create(obligation=ob, competence=competence, done_by=actor,
                                                    note=(note or '')[:255])
        except IntegrityError as exc:
            raise ActionError('Esta competência já está marcada como feita.') from exc
    audit.log('fiscal.obligation_done', actor=actor, target=ob, changes={'competencia': competence, 'desfeito': bool(undo)},
              legal_basis='obrigacao_legal')


def remind(today=None) -> int:
    """Avisa a equipe Fiscal (sino) 5 dias e 1 dia antes, e no dia seguinte ao atraso. Idempotente (dedupe por competência/dia)."""
    from django.contrib.auth.models import Group

    from backoffice.permissions import AREA_GROUPS
    from notifications.models import Notification
    today = today or timezone.localdate()
    users = list(Group.objects.filter(name=AREA_GROUPS['fiscal']).values_list('user__id', flat=True))
    users = [u for u in users if u]
    sent = 0
    for r in upcoming(today, days=6):
        if r['situacao'] == 'feito' or r['dias'] not in (5, 1, -1):
            continue
        title = (f'{r["nome"]} vence em {r["dias"]} dia(s)' if r['dias'] > 0 else f'{r["nome"]} está atrasada')
        for uid in users:
            _, created = Notification.objects.get_or_create(
                user_id=uid, dedupe_key=f'fiscal:{r["codigo"]}:{r["competencia"]}:{r["dias"]}',
                defaults={'type': Notification.Type.PRAZO, 'title': title[:255],
                          'description': f'Competência {r["competencia"]}, vencimento {r["vencimento"]:%d/%m/%Y}.',
                          'link': '/gestao/fiscal?aba=obrigacoes'})
            sent += created
    return sent
