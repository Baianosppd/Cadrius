"""Relatórios do financeiro e do fiscal do escritório (CAD-223): fluxo de caixa projetado, inadimplência por faixa,
meta do mês, DRE mensal, estimativa de impostos por regime, pacote do contador e despesas recorrentes.

As estimativas de imposto são orientativas (a tela diz "confirme com o contador"): usam só a receita registrada no Cadrius.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from carteira.models import Expense, FinanceSettings, Receivable, RecurringExpense
from carteira.services import FinanceError, add_months

# Simples Nacional — Anexo IV (LC 123/2006, redação da LC 155/2016): advocacia. Sem CPP (INSS patronal é pago à parte).
ANEXO_IV = [(180_000_00, Decimal('0.045'), 0), (360_000_00, Decimal('0.09'), 8_100_00), (720_000_00, Decimal('0.102'), 12_420_00),
            (1_800_000_00, Decimal('0.14'), 39_780_00), (3_600_000_00, Decimal('0.22'), 183_780_00),
            (4_800_000_00, Decimal('0.33'), 828_000_00)]
# Lucro Presumido para serviços: presunção de 32% → IRPJ 15% (4,8%) + CSLL 9% (2,88%) + PIS 0,65% + COFINS 3% (cumulativos).
PRESUMIDO = {'irpj': Decimal('0.048'), 'csll': Decimal('0.0288'), 'pis': Decimal('0.0065'), 'cofins': Decimal('0.03')}
AVISO = ('Estimativa com a receita registrada no Cadrius (regime de caixa). Não substitui o cálculo do contador: confira '
         'retenções, adicional de IRPJ, folha (Fator R não se aplica à advocacia) e mudanças da reforma tributária (CBS/IBS).')


def _sum(qs, field='amount_cents'):
    return qs.aggregate(t=Sum(field))['t'] or 0


def month_key(d: date) -> str:
    return d.strftime('%Y-%m')


# ----------------------------------------------------------------------------- despesas recorrentes
def generate_recurring(today: date | None = None) -> int:
    """Lança as despesas fixas do mês (idempotente por mês). Roda todo dia; lança a partir do dia configurado."""
    today = today or timezone.localdate()
    key, made = month_key(today), 0
    qs = RecurringExpense.objects.filter(active=True, starts_on__lte=today, organization__is_active=True).exclude(last_month=key)
    for r in qs.select_related('organization'):
        if r.ends_on and r.ends_on < today.replace(day=1):
            continue
        if today.day < min(r.day, 28):
            continue
        exp = Expense.objects.create(organization=r.organization, description=f'{r.description} ({today:%m/%Y})', category=r.category,
                                     amount_cents=r.amount_cents, date=today.replace(day=min(r.day, 28)), created_by=r.created_by)
        from automations.engine import emit
        emit(r.organization, 'expense_created', {'expense_id': exp.pk}, f'expense-{exp.pk}')
        r.last_month = key
        r.save(update_fields=['last_month'])
        made += 1
    return made


def recurring_json(r: RecurringExpense) -> dict:
    return {'id': r.pk, 'descricao': r.description, 'categoria': r.category, 'categoria_label': r.get_category_display(),
            'valor_centavos': r.amount_cents, 'dia': r.day, 'ativa': r.active, 'inicio': r.starts_on, 'fim': r.ends_on,
            'ultimo_mes': r.last_month}


def _recurring_in(org, start: date, end: date) -> list[tuple[date, int, str]]:
    """Ocorrências projetadas das despesas fixas entre ``start`` e ``end`` (ainda não lançadas)."""
    out = []
    for r in RecurringExpense.objects.filter(organization=org, active=True):
        d = start.replace(day=1)
        while d <= end:
            when = d.replace(day=min(r.day, 28))
            if start <= when <= end and when >= r.starts_on and (not r.ends_on or when <= r.ends_on) and r.last_month != month_key(when):
                out.append((when, r.amount_cents, r.description))
            d = add_months(d, 1)
    return out


# ----------------------------------------------------------------------------- fluxo de caixa e indicadores
def cash_flow(org, weeks: int = 12, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    weeks = max(4, min(int(weeks or 12), 26))
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(weeks=weeks) - timedelta(days=1)
    rec = Receivable.objects.filter(organization=org, status=Receivable.Status.OPEN)
    overdue = _sum(rec.filter(due_date__lt=today))
    buckets = [{'semana': start + timedelta(weeks=i), 'entradas': 0, 'saidas': 0} for i in range(weeks)]

    def put(d, field, cents):
        idx = (d - start).days // 7
        if 0 <= idx < weeks:
            buckets[idx][field] += cents
    for r in rec.filter(due_date__gte=today, due_date__lte=end).values('due_date', 'amount_cents'):
        put(r['due_date'], 'entradas', r['amount_cents'])
    for e in Expense.objects.filter(organization=org, date__gte=today, date__lte=end, reimbursable=False).values('date', 'amount_cents'):
        put(e['date'], 'saidas', e['amount_cents'])
    for when, cents, _ in _recurring_in(org, today, end):
        put(when, 'saidas', cents)
    acc = 0
    for b in buckets:
        acc += b['entradas'] - b['saidas']
        b['saldo_acumulado'] = acc
    return {'semanas': buckets, 'vencido_centavos': overdue, 'entradas_centavos': sum(b['entradas'] for b in buckets),
            'saidas_centavos': sum(b['saidas'] for b in buckets), 'aviso': 'Previsão: parcelas em aberto pelo vencimento, '
            'despesas já lançadas e despesas fixas. Vencidos ficam fora (somados à parte).'}


def aging(org, today: date | None = None) -> list[dict]:
    today = today or timezone.localdate()
    faixas = [('a_vencer', None, -1), ('1_30', 1, 30), ('31_60', 31, 60), ('61_90', 61, 90), ('90_mais', 91, None)]
    out = []
    qs = Receivable.objects.filter(organization=org, status=Receivable.Status.OPEN)
    for key, lo, hi in faixas:
        f = qs
        if key == 'a_vencer':
            f = f.filter(due_date__gte=today)
        else:
            f = f.filter(due_date__lte=today - timedelta(days=lo))
            if hi:
                f = f.filter(due_date__gte=today - timedelta(days=hi))
        out.append({'faixa': key, 'parcelas': f.count(), 'centavos': _sum(f)})
    return out


def goal(org, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    cfg = FinanceSettings.of(org)
    first = today.replace(day=1)
    last = add_months(first, 1) - timedelta(days=1)
    paid = _sum(Receivable.objects.filter(organization=org, status=Receivable.Status.PAID, paid_at__gte=first, paid_at__lte=today),
                'paid_cents')
    expected = _sum(Receivable.objects.filter(organization=org, status=Receivable.Status.OPEN, due_date__gte=today, due_date__lte=last))
    target = cfg.monthly_goal_cents
    return {'meta_centavos': target, 'recebido_centavos': paid, 'previsto_restante_centavos': expected,
            'pct': round(100 * paid / target) if target else None,
            'projecao_pct': round(100 * (paid + expected) / target) if target else None}


def dre(org, year: int | None = None) -> dict:
    """Demonstrativo mensal simples (caixa): receitas recebidas, despesas por categoria e resultado."""
    year = int(year or timezone.localdate().year)
    months = {f'{year}-{m:02d}': {'receitas': 0, 'despesas': 0, 'categorias': defaultdict(int)} for m in range(1, 13)}
    for r in Receivable.objects.filter(organization=org, status=Receivable.Status.PAID, paid_at__year=year).values('paid_at', 'paid_cents'):
        months[month_key(r['paid_at'])]['receitas'] += r['paid_cents']
    for e in Expense.objects.filter(organization=org, date__year=year, reimbursable=False).values('date', 'amount_cents', 'category'):
        row = months[month_key(e['date'])]
        row['despesas'] += e['amount_cents']
        row['categorias'][e['category']] += e['amount_cents']
    labels = dict(Expense.Category.choices)
    rows = [{'mes': k, 'receitas': v['receitas'], 'despesas': v['despesas'], 'resultado': v['receitas'] - v['despesas'],
             'categorias': [{'categoria': c, 'rotulo': labels.get(c, c), 'centavos': t} for c, t in sorted(v['categorias'].items())]}
            for k, v in months.items()]
    total_r, total_d = sum(r['receitas'] for r in rows), sum(r['despesas'] for r in rows)
    return {'ano': year, 'meses': rows, 'receitas': total_r, 'despesas': total_d, 'resultado': total_r - total_d,
            'margem_pct': round(100 * (total_r - total_d) / total_r) if total_r else None}


# ----------------------------------------------------------------------------- fiscal do escritório
def simples_rate(rbt12_cents: int) -> Decimal:
    if rbt12_cents <= 0:
        return ANEXO_IV[0][1]
    for limit, aliq, pd in ANEXO_IV:
        if rbt12_cents <= limit:
            return ((Decimal(rbt12_cents) * aliq - pd) / Decimal(rbt12_cents)).quantize(Decimal('0.0001'))
    raise FinanceError('Receita acima do limite do Simples Nacional (R$ 4,8 milhões em 12 meses).')


def fiscal(org, month: date | None = None) -> dict:
    """Receita do mês (por tipo de pagador), RBT12 e imposto estimado pelo regime escolhido."""
    month = (month or timezone.localdate()).replace(day=1)
    end = add_months(month, 1) - timedelta(days=1)
    cfg = FinanceSettings.of(org)
    paid = Receivable.objects.filter(organization=org, status=Receivable.Status.PAID)
    in_month = paid.filter(paid_at__gte=month, paid_at__lte=end).select_related('contact')
    pf = sum(r.paid_cents for r in in_month if r.contact.person_type == 'PF')
    pj = sum(r.paid_cents for r in in_month if r.contact.person_type != 'PF')
    receita = pf + pj
    rbt12 = _sum(paid.filter(paid_at__gte=add_months(month, -12), paid_at__lt=month), 'paid_cents')
    iss = (Decimal(receita) * cfg.iss_pct / 100).quantize(Decimal('1'))
    est = {'regime': cfg.regime, 'regime_label': cfg.get_regime_display(), 'itens': []}
    if cfg.regime == FinanceSettings.Regime.SIMPLES:
        try:
            rate = simples_rate(rbt12)
            est['itens'] = [{'nome': f'DAS — Simples Anexo IV (alíquota efetiva {rate * 100:.2f}%)',
                             'centavos': int((Decimal(receita) * rate).quantize(Decimal('1')))},
                            {'nome': 'INSS patronal (CPP) sobre a folha/pró-labore — fora do DAS no Anexo IV', 'centavos': None}]
        except FinanceError as exc:
            est['alerta'] = str(exc)
    elif cfg.regime == FinanceSettings.Regime.PRESUMIDO:
        est['itens'] = [{'nome': n.upper(), 'centavos': int((Decimal(receita) * t).quantize(Decimal('1')))} for n, t in PRESUMIDO.items()]
        est['itens'].append({'nome': f'ISS ({cfg.iss_pct}%)', 'centavos': int(iss)})
    elif cfg.regime == FinanceSettings.Regime.AUTONOMO:
        est['itens'] = [{'nome': 'Carnê-Leão: receita de pessoas físicas no mês (base para o recolhimento)', 'centavos': pf},
                        {'nome': 'Recebido de empresas (normalmente com IR retido na fonte)', 'centavos': pj}]
        est['dica'] = 'Lance no Carnê-Leão Web (gov.br) até o último dia útil do mês seguinte, com o CPF de cada pagador.'
    elif cfg.regime == FinanceSettings.Regime.UNIPROFISSIONAL:
        est['itens'] = [{'nome': 'ISS fixo por profissional (valor definido pelo município)', 'centavos': None}]
    est['total_centavos'] = sum(i['centavos'] or 0 for i in est['itens'] if cfg.regime != FinanceSettings.Regime.AUTONOMO)
    pending_nfse = in_month.filter(nfse_id='').count()
    return {'mes': month_key(month), 'receita_centavos': receita, 'pessoa_fisica_centavos': pf, 'pessoa_juridica_centavos': pj,
            'rbt12_centavos': rbt12, 'estimativa': est, 'sem_nota': pending_nfse, 'aviso': AVISO,
            'config': settings_json(cfg)}


def settings_json(cfg: FinanceSettings) -> dict:
    return {'meta_mensal_centavos': cfg.monthly_goal_cents, 'regime': cfg.regime, 'regimes': FinanceSettings.Regime.choices,
            'iss_pct': str(cfg.iss_pct), 'descricao_servico': cfg.service_description,
            'codigo_servico_municipal': cfg.municipal_service_code, 'nome_servico_municipal': cfg.municipal_service_name,
            'email_contador': cfg.accountant_email}


def accountant_csv(org, start: date, end: date) -> str:
    """Pacote do contador: recebimentos (com CPF/CNPJ do pagador, exigido no Carnê-Leão) e despesas do período."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['tipo', 'data', 'descricao', 'pessoa', 'tipo_pessoa', 'cpf_cnpj', 'categoria', 'forma', 'valor', 'nfse'])
    for r in (Receivable.objects.filter(organization=org, status=Receivable.Status.PAID, paid_at__gte=start, paid_at__lte=end)
              .select_related('contact').order_by('paid_at')):
        w.writerow(['receita', r.paid_at.isoformat(), r.description, r.contact.name, r.contact.person_type, r.contact.document or '',
                    'honorarios', r.method, f'{Decimal(r.paid_cents) / 100:.2f}'.replace('.', ','), r.nfse_status or ''])
    for e in Expense.objects.filter(organization=org, date__gte=start, date__lte=end).select_related('contact').order_by('date'):
        w.writerow(['despesa', e.date.isoformat(), e.description, e.contact.name if e.contact else '', '', '', e.category,
                    'reembolsavel' if e.reimbursable else '', f'-{Decimal(e.amount_cents) / 100:.2f}'.replace('.', ','), ''])
    return buf.getvalue()
