"""Regras da carteira e do financeiro do escritório (CAD-175)."""
from __future__ import annotations

import calendar
import hmac
import re
import secrets
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from audit import service as audit
from carteira.models import AsaasEvent, Expense, FeeAgreement, Opportunity, Receivable

MAX_CENTS = 100_000_000_00          # R$ 100 milhões
MAX_INSTALLMENTS = 120


class FinanceError(ValueError):
    pass


# ----------------------------------------------------------------------------- dinheiro e datas
def to_cents(value, *, allow_zero=False) -> int:
    """Aceita 1234.56, "1234,56", "1.234,56", "R$ 1.234,56" ou centavos inteiros com a chave *_centavos (tratada na API)."""
    if value is None or value == '':
        if allow_zero:
            return 0
        raise FinanceError('Informe o valor.')
    if isinstance(value, (int, float, Decimal)):
        dec = Decimal(str(value))
    else:
        raw = re.sub(r'[^\d,.\-]', '', str(value))
        if ',' in raw:
            raw = raw.replace('.', '').replace(',', '.')
        try:
            dec = Decimal(raw)
        except InvalidOperation as exc:
            raise FinanceError('Valor inválido.') from exc
    cents = int((dec * 100).quantize(Decimal('1')))
    if cents < 0 or cents > MAX_CENTS or (cents == 0 and not allow_zero):
        raise FinanceError('Valor fora do limite (maior que zero e até R$ 100 milhões).')
    return cents


def brl(cents: int) -> str:
    s = f'{(cents or 0) / 100:,.2f}'
    return 'R$ ' + s.replace(',', 'X').replace('.', ',').replace('X', '.')


def to_date(value, field='data') -> date:
    try:
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError as exc:
        raise FinanceError(f'Informe a {field} no formato AAAA-MM-DD.') from exc


def add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def split(total: int, n: int) -> list:
    """Divide em N parcelas inteiras; a diferença de centavos vai na 1ª."""
    base = total // n
    return [base + (total - base * n)] + [base] * (n - 1)


# ----------------------------------------------------------------------------- funil
def move_stage(opp: Opportunity, stage: str, user, lost_reason=''):
    if stage not in Opportunity.Stage.values:
        raise FinanceError('Etapa inválida.')
    if stage == Opportunity.Stage.LOST and not (lost_reason or opp.lost_reason).strip():
        raise FinanceError('Diga por que não fechou: ajuda a melhorar a captação.')
    old = opp.stage
    opp.stage, opp.stage_changed_at = stage, timezone.now()
    if stage == Opportunity.Stage.LOST:
        opp.lost_reason = (lost_reason or opp.lost_reason).strip()[:200]
    opp.closed_at = timezone.now() if stage in (Opportunity.Stage.WON, Opportunity.Stage.LOST) else None
    opp.save()
    if old != stage:
        audit.log('crm.stage_changed', actor=user, organization=opp.organization, target=opp, changes={'de': old, 'para': stage})
        from automations.engine import emit
        emit(opp.organization, 'opportunity_stage', {'opportunity_id': opp.pk, 'de': old}, f'opp-{opp.pk}-{stage}-{int(opp.stage_changed_at.timestamp())}')
    return opp


def funnel(org, days=90) -> dict:
    since = timezone.now() - timedelta(days=days)
    qs = Opportunity.objects.filter(organization=org)
    stages = {row['stage']: {'quantidade': row['n'], 'valor_centavos': row['v'] or 0}
              for row in qs.values('stage').annotate(n=Count('id'), v=Sum('value_cents'))}
    closed = qs.filter(closed_at__gte=since)
    won, lost = closed.filter(stage=Opportunity.Stage.WON).count(), closed.filter(stage=Opportunity.Stage.LOST).count()
    sources = {}
    for row in qs.filter(created_at__gte=since).values('source').annotate(n=Count('id'), w=Count('id', filter=Q(stage='ganho'))):
        sources[row['source']] = {'quantidade': row['n'], 'ganhos': row['w']}
    reasons = list(closed.filter(stage=Opportunity.Stage.LOST).exclude(lost_reason='').values('lost_reason')
                   .annotate(n=Count('id')).order_by('-n')[:5])
    late = qs.filter(stage__in=Opportunity.OPEN_STAGES, next_action_at__lt=timezone.localdate()).count()
    return {'por_etapa': stages, 'ganhos': won, 'perdidos': lost, 'conversao_pct': round(100 * won / (won + lost)) if won + lost else None,
            'por_origem': sources, 'motivos_perda': [{'motivo': r['lost_reason'], 'quantidade': r['n']} for r in reasons],
            'acoes_atrasadas': late, 'dias': days}


# ----------------------------------------------------------------------------- contratos e parcelas
def schedule_for(kind, total, installments, first_due) -> list:
    """[(descrição, centavos, vencimento)] das parcelas que o contrato gera."""
    if kind in (FeeAgreement.Kind.SUCCESS,):
        return []
    if not total:
        raise FinanceError('Informe o valor dos honorários.')
    if first_due is None:
        raise FinanceError('Informe o 1º vencimento.')
    n = installments if kind in (FeeAgreement.Kind.INSTALLMENTS, FeeAgreement.Kind.MONTHLY, FeeAgreement.Kind.MIXED) else 1
    if not 1 <= n <= MAX_INSTALLMENTS:
        raise FinanceError(f'Parcelas entre 1 e {MAX_INSTALLMENTS}.')
    if kind == FeeAgreement.Kind.MONTHLY:
        return [(f'Mensalidade {i + 1}/{n}', total, add_months(first_due, i)) for i in range(n)]
    label = 'Entrada' if kind == FeeAgreement.Kind.MIXED else 'Parcela'
    if n == 1:
        return [('Honorários' if kind == FeeAgreement.Kind.UPFRONT else label, total, first_due)]
    return [(f'{label} {i + 1}/{n}', v, add_months(first_due, i)) for i, v in enumerate(split(total, n))]


@transaction.atomic
def create_agreement(org, user, *, contact, title, kind, total_cents=0, installments=1, first_due=None, success_pct=0,
                     case=None, opportunity=None, notes='') -> FeeAgreement:
    if kind not in FeeAgreement.Kind.values:
        raise FinanceError('Tipo de contrato inválido.')
    pct = Decimal(str(success_pct or 0))
    if kind in (FeeAgreement.Kind.SUCCESS, FeeAgreement.Kind.MIXED) and not Decimal('0') < pct <= Decimal('100'):
        raise FinanceError('Informe o percentual de êxito (até 100%).')
    rows = schedule_for(kind, total_cents, installments, first_due)
    ag = FeeAgreement.objects.create(organization=org, contact=contact, case=case, opportunity=opportunity, title=title[:160], kind=kind,
                                     total_cents=total_cents, installments=installments or 1, first_due=first_due, success_pct=pct,
                                     notes=notes, created_by=user)
    Receivable.objects.bulk_create([
        Receivable(organization=org, agreement=ag, contact=contact, case=case, description=f'{desc} — {ag.title}'[:200],
                   amount_cents=cents, due_date=due, created_by=user) for desc, cents, due in rows])
    if opportunity and opportunity.stage != Opportunity.Stage.WON:
        move_stage(opportunity, Opportunity.Stage.WON, user)
    audit.log('crm.agreement_created', actor=user, organization=org, target=ag,
              changes={'tipo': kind, 'parcelas': len(rows), 'total_centavos': sum(r[1] for r in rows)},
              data_categories=['financeiro'], legal_basis='execucao_contrato')
    from automations.engine import emit
    emit(org, 'agreement_created', {'agreement_id': ag.pk}, f'agreement-{ag.pk}')
    return ag


def register_success(ag: FeeAgreement, user, *, benefit_cents: int, due_date: date) -> Receivable:
    """Êxito: o proveito econômico apurado vira um lançamento a receber pelo percentual do contrato."""
    if ag.kind not in (FeeAgreement.Kind.SUCCESS, FeeAgreement.Kind.MIXED):
        raise FinanceError('Este contrato não tem honorários de êxito.')
    cents = int((Decimal(benefit_cents) * ag.success_pct / 100).quantize(Decimal('1')))
    if cents <= 0:
        raise FinanceError('O proveito informado não gera honorários.')
    rec = Receivable.objects.create(organization=ag.organization, agreement=ag, contact=ag.contact, case=ag.case,
                                    description=f'Êxito ({ag.success_pct}% de {brl(benefit_cents)}) — {ag.title}'[:200],
                                    amount_cents=cents, due_date=due_date, created_by=user)
    audit.log('crm.success_registered', actor=user, organization=ag.organization, target=ag,
              changes={'proveito_centavos': benefit_cents, 'honorarios_centavos': cents}, data_categories=['financeiro'])
    return rec


def cancel_agreement(ag: FeeAgreement, user):
    with transaction.atomic():
        ag.status = FeeAgreement.Status.CANCELED
        ag.save(update_fields=['status', 'updated_at'])
        n = ag.receivables.filter(status=Receivable.Status.OPEN).update(status=Receivable.Status.CANCELED)
    audit.log('crm.agreement_canceled', actor=user, organization=ag.organization, target=ag, changes={'parcelas_canceladas': n})
    return n


def mark_paid(rec: Receivable, user, *, paid_at=None, paid_cents=None, method='', source='manual'):
    if rec.status == Receivable.Status.CANCELED:
        raise FinanceError('Lançamento cancelado não pode receber baixa.')
    rec.status = Receivable.Status.PAID
    rec.paid_at = paid_at or timezone.localdate()
    rec.paid_cents = paid_cents or rec.amount_cents
    if method in Receivable.Method.values:
        rec.method = method
    rec.save(update_fields=['status', 'paid_at', 'paid_cents', 'method', 'updated_at'])
    audit.log('finance.receivable_paid', actor=user, organization=rec.organization, target=rec,
              changes={'valor_centavos': rec.paid_cents, 'forma': rec.method, 'origem': source}, data_categories=['financeiro'])
    _close_if_done(rec.agreement)
    from automations.engine import emit
    emit(rec.organization, 'receivable_paid', {'receivable_id': rec.pk}, f'paid-{rec.pk}-{rec.paid_at.isoformat()}')
    return rec


def reopen(rec: Receivable, user):
    rec.status, rec.paid_at, rec.paid_cents = Receivable.Status.OPEN, None, 0
    rec.save(update_fields=['status', 'paid_at', 'paid_cents', 'updated_at'])
    audit.log('finance.receivable_reopened', actor=user, organization=rec.organization, target=rec)
    if rec.agreement_id and rec.agreement.status == FeeAgreement.Status.DONE:
        FeeAgreement.objects.filter(pk=rec.agreement_id).update(status=FeeAgreement.Status.ACTIVE)
    return rec


def _close_if_done(ag):
    if ag is None or ag.kind in (FeeAgreement.Kind.SUCCESS, FeeAgreement.Kind.MIXED) or ag.status != FeeAgreement.Status.ACTIVE:
        return
    if not ag.receivables.filter(status=Receivable.Status.OPEN).exists():
        ag.status = FeeAgreement.Status.DONE
        ag.save(update_fields=['status', 'updated_at'])


def create_expense(org, user, *, description, category, amount_cents, when, case=None, contact=None, reimbursable=False) -> Expense:
    if category not in Expense.Category.values:
        raise FinanceError('Categoria inválida.')
    if reimbursable and contact is None and not (case and case.client_id):
        raise FinanceError('Para reembolso, informe o cliente (ou um processo com cliente vinculado).')
    with transaction.atomic():
        exp = Expense.objects.create(organization=org, description=description[:200], category=category, amount_cents=amount_cents,
                                     date=when, case=case, contact=contact or (case.client if case else None),
                                     reimbursable=reimbursable, created_by=user)
        if reimbursable:
            exp.reimbursement = Receivable.objects.create(
                organization=org, contact=exp.contact, case=case, description=f'Reembolso: {description}'[:200], amount_cents=amount_cents,
                due_date=max(when, timezone.localdate()) + timedelta(days=10), created_by=user)
            exp.save(update_fields=['reimbursement'])
    audit.log('finance.expense_created', actor=user, organization=org, target=exp,
              changes={'categoria': category, 'valor_centavos': amount_cents, 'reembolsavel': reimbursable}, data_categories=['financeiro'])
    return exp


# ----------------------------------------------------------------------------- painel
def summary(org, start: date, end: date) -> dict:
    today = timezone.localdate()
    rec = Receivable.objects.filter(organization=org)
    open_qs = rec.filter(status=Receivable.Status.OPEN)
    overdue = open_qs.filter(due_date__lt=today)
    paid = rec.filter(status=Receivable.Status.PAID, paid_at__gte=start, paid_at__lte=end)
    exp = Expense.objects.filter(organization=org, date__gte=start, date__lte=end)
    total = lambda qs, f='amount_cents': qs.aggregate(t=Sum(f))['t'] or 0   # noqa: E731
    open_total, overdue_total = total(open_qs), total(overdue)
    paid_total = total(paid, 'paid_cents')
    office_exp = total(exp.filter(reimbursable=False))
    months = defaultdict(lambda: {'recebido': 0, 'despesas': 0})
    for r in paid.values('paid_at', 'paid_cents'):
        months[r['paid_at'].strftime('%Y-%m')]['recebido'] += r['paid_cents']
    for e in exp.filter(reimbursable=False).values('date', 'amount_cents'):
        months[e['date'].strftime('%Y-%m')]['despesas'] += e['amount_cents']
    # margem por cliente no período: recebido − despesas não reembolsáveis atribuídas a ele
    by_client = defaultdict(lambda: {'recebido': 0, 'despesas': 0, 'nome': ''})
    for r in paid.select_related('contact'):
        by_client[r.contact_id]['recebido'] += r.paid_cents
        by_client[r.contact_id]['nome'] = r.contact.name
    for e in exp.filter(reimbursable=False, contact__isnull=False).select_related('contact'):
        by_client[e.contact_id]['despesas'] += e.amount_cents
        by_client[e.contact_id]['nome'] = e.contact.name
    clients = sorted(({'contato_id': k, **v, 'margem': v['recebido'] - v['despesas']} for k, v in by_client.items()),
                     key=lambda x: -x['recebido'])[:10]
    return {
        'periodo': {'inicio': start, 'fim': end},
        'a_receber_centavos': open_total, 'vencido_centavos': overdue_total, 'vencidos': overdue.count(),
        'inadimplencia_pct': round(100 * overdue_total / open_total) if open_total else 0,
        'previsto_30_dias_centavos': total(open_qs.filter(due_date__gte=today, due_date__lte=today + timedelta(days=30))),
        'recebido_centavos': paid_total, 'despesas_centavos': office_exp,
        'reembolsaveis_centavos': total(exp.filter(reimbursable=True)),
        'resultado_centavos': paid_total - office_exp,
        'por_mes': [{'mes': k, **v} for k, v in sorted(months.items())],
        'por_categoria': [{'categoria': r['category'], 'centavos': r['t']} for r in
                          exp.values('category').annotate(t=Sum('amount_cents')).order_by('-t')],
        'clientes': clients,
    }


# ----------------------------------------------------------------------------- Asaas (cobrança + baixa automática)
def charge(rec: Receivable, user, billing_type='UNDEFINED') -> Receivable:
    from integrations import services as integ
    if rec.status != Receivable.Status.OPEN:
        raise FinanceError('Só lançamentos em aberto podem virar cobrança.')
    if rec.asaas_id:
        raise FinanceError('Este lançamento já tem cobrança no Asaas.')
    conn = integ.org_connection(rec.organization, 'ASAAS')
    if conn is None:
        raise FinanceError('Conecte o Asaas em Integrações primeiro.')
    due = max(rec.due_date, timezone.localdate())
    result = integ.asaas_charge(conn.credentials or {}, contact=rec.contact, value=Decimal(rec.amount_cents) / 100, due_date=due,
                                description=rec.description, billing_type=billing_type)
    rec.asaas_id, rec.payment_url = result.get('id', '')[:40], (result.get('link') or result.get('boleto') or '')[:500]
    rec.save(update_fields=['asaas_id', 'payment_url', 'updated_at'])
    audit.log('billing.charge_created', actor=user, organization=rec.organization, target=rec,
              changes={'provedor': 'asaas', 'valor_centavos': rec.amount_cents, 'forma': billing_type},
              data_categories=['identificacao', 'financeiro'], legal_basis='execucao_contrato')
    return rec


def webhook_config(conn) -> str:
    """Gera (ou devolve) o token que o Asaas manda no cabeçalho asaas-access-token."""
    creds = dict(conn.credentials or {})
    if not creds.get('webhook_token'):
        creds['webhook_token'] = secrets.token_urlsafe(36)
        conn.credentials = creds
        conn.save(update_fields=['credentials'])
    return creds['webhook_token']


PAID_EVENTS = {'PAYMENT_RECEIVED', 'PAYMENT_CONFIRMED', 'PAYMENT_RECEIVED_IN_CASH'}
REOPEN_EVENTS = {'PAYMENT_REFUNDED', 'PAYMENT_CHARGEBACK_REQUESTED', 'PAYMENT_RECEIVED_IN_CASH_UNDONE'}
CANCEL_EVENTS = {'PAYMENT_DELETED'}


def token_ok(conn, given: str) -> bool:
    expected = (conn.credentials or {}).get('webhook_token') or ''
    return bool(expected) and hmac.compare_digest(expected, given or '')


def handle_asaas_event(org, payload: dict) -> str:
    """Processa um evento do webhook. Idempotente pelo id do evento. Devolve o que foi feito (para log/teste)."""
    event = str(payload.get('event') or '')[:40]
    payment = payload.get('payment') or {}
    pay_id = str(payment.get('id') or '')[:40]
    event_id = str(payload.get('id') or f'{event}:{pay_id}')[:80]
    try:
        with transaction.atomic():
            AsaasEvent.objects.create(organization=org, event_id=event_id, event=event, payment_id=pay_id)
    except IntegrityError:
        return 'duplicado'
    rec = Receivable.objects.filter(organization=org, asaas_id=pay_id).first() if pay_id else None
    if rec is None:
        return 'ignorado'
    if event in PAID_EVENTS and rec.status != Receivable.Status.PAID:
        method = {'PIX': 'pix', 'BOLETO': 'boleto', 'CREDIT_CARD': 'cartao'}.get(str(payment.get('billingType') or ''), 'outro')
        paid_on = payment.get('paymentDate') or payment.get('clientPaymentDate') or payment.get('confirmedDate')
        try:
            paid_on = date.fromisoformat(str(paid_on)) if paid_on else None
        except ValueError:
            paid_on = None
        try:
            cents = to_cents(payment.get('value')) if payment.get('value') is not None else None
        except FinanceError:
            cents = None
        mark_paid(rec, None, paid_at=paid_on, paid_cents=cents, method=method, source='asaas')
        return 'pago'
    if event in REOPEN_EVENTS and rec.status == Receivable.Status.PAID:
        reopen(rec, None)
        return 'reaberto'
    if event in CANCEL_EVENTS and rec.status == Receivable.Status.OPEN:
        rec.status = Receivable.Status.CANCELED
        rec.save(update_fields=['status', 'updated_at'])
        return 'cancelado'
    return 'sem_mudanca'


# ----------------------------------------------------------------------------- régua de cobrança (gatilho de automação)
def due_targets(today: date, when: str, days: int) -> date:
    return today + timedelta(days=days) if when == 'antes' else today - timedelta(days=days)


def overdue_days(rec: Receivable, today=None) -> int:
    today = today or timezone.localdate()
    return max((today - rec.due_date).days, 0)
