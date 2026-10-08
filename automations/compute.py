"""Processamento dentro das regras (CAD-230): cálculos e tabelas temporárias.

Antes a regra só renderizava variáveis do evento em textos. Agora um passo pode **calcular** e **montar uma tabela** que os
passos seguintes usam — tudo durante o planejamento (sem efeito colateral, então a simulação mostra os números):

- ``calcular``: expressão aritmética com as variáveis do evento e funções em português, ex.
  ``{{honorario.valor}} * 0,02 + {{honorario.valor}} * 0,00033 * {{honorario.dias_atraso}}`` → ``{{calc.multa}}``.
  Avaliada por uma árvore sintática restrita (só números, + − × ÷, comparações e as funções da lista): sem ``eval``,
  sem atributos, sem acesso a nada do Python.
- ``tabela``: lista temporária vinda dos dados do escritório (honorários em aberto, tarefas, prazos da semana, processos
  parados, despesas do mês, oportunidades abertas), filtrada pelo cliente do evento quando se quer. Expõe
  ``{{tabela.<nome>.quantidade}}``, ``.total``, ``.texto`` (lista pronta para mensagem) e as linhas, que vão para a
  planilha do Google. Existe só durante a execução: nada é gravado além do que as ações seguintes fizerem.
"""
from __future__ import annotations

import ast
import operator
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

VAR = re.compile(r'\{\{\s*([a-z_][a-z0-9_.]*)\s*\}\}')
NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,29}$')
MAX_EXPR = 400
MAX_ROWS = 200


class ComputeError(ValueError):
    """Mensagem pronta para a tela."""


# ----------------------------------------------------------------------------- números e datas em português
def to_number(value):
    """'R$ 1.234,56' / '1234.56' / '15%' / 12 → Decimal. Vazio → 0. Texto que não é número → ComputeError."""
    if value is None or value == '':
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip().replace('R$', '').replace('\xa0', '').replace(' ', '')
    pct = text.endswith('%')
    text = text.rstrip('%')
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        n = Decimal(text)
    except InvalidOperation as exc:
        raise ComputeError(f'"{value}" não é um número.') from exc
    return n / 100 if pct else n


def to_date(value):
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    raise ComputeError(f'"{value}" não é uma data (use dd/mm/aaaa).')


def money(n) -> str:
    s = f'{Decimal(n):,.2f}'
    return 'R$ ' + s.replace(',', 'X').replace('.', ',').replace('X', '.')


def fmt(n, kind='numero') -> str:
    n = Decimal(n)
    if kind == 'moeda':
        return money(n)
    if kind == 'inteiro':
        return str(int(n.to_integral_value()))
    if kind == 'percentual':
        return f'{(n * 100).quantize(Decimal("0.01"))}%'.replace('.', ',')
    q = n.quantize(Decimal('0.01')) if n != n.to_integral_value() else n.to_integral_value()
    return str(q).replace('.', ',')


# ----------------------------------------------------------------------------- avaliador seguro
def _dias_entre(a, b):
    return Decimal((to_date(b) - to_date(a)).days)


FUNCS = {
    'arredondar': lambda x, casas=2: Decimal(x).quantize(Decimal(1).scaleb(-int(casas))),
    'minimo': lambda *xs: min(Decimal(x) for x in xs),
    'maximo': lambda *xs: max(Decimal(x) for x in xs),
    'soma': lambda *xs: sum((Decimal(x) for x in xs), Decimal(0)),
    'media': lambda *xs: sum((Decimal(x) for x in xs), Decimal(0)) / len(xs) if xs else Decimal(0),
    'abs': lambda x: abs(Decimal(x)),
    'se': lambda cond, sim, nao=0: sim if cond else nao,
}
DATE_FUNCS = {'dias_entre'}
BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
          ast.Pow: operator.pow}                              # "%" é percentual (2% = 0,02), não resto da divisão
CMPOPS = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Eq: operator.eq,
          ast.NotEq: operator.ne}
HELP_FUNCS = ('arredondar(x; casas), minimo(a; b…), maximo(a; b…), soma(…), media(…), abs(x), se(condição; sim; não), '
              'dias_entre(data1; data2)')


def _prepare(expr: str, ctx: dict):
    """Troca as variáveis por nomes v0, v1… e a vírgula decimal por ponto. Vírgula ENTRE DÍGITOS é decimal (0,02); para separar
    argumentos use "; " ou ", " com espaço — como no Excel em português: arredondar(x; 2)."""
    from automations.engine import resolve
    values, names = {}, {}

    def _sub(m):
        path = m.group(1)
        if path not in names:
            names[path] = f'v{len(names)}'
            values[names[path]] = resolve(ctx, path)
        return names[path]
    text = VAR.sub(_sub, expr)
    text = re.sub(r'(?<=\d),(?=\d)', '.', text)                 # 0,02 → 0.02
    text = text.replace(';', ',')                                # separador de argumentos à moda do Excel pt-BR
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'(\1/100)', text)     # 2% → (2/100)
    return text, values


def evaluate(expr: str, ctx: dict) -> Decimal:
    expr = (expr or '').strip()
    if not expr:
        raise ComputeError('Escreva a conta.')
    if len(expr) > MAX_EXPR:
        raise ComputeError(f'A conta passou de {MAX_EXPR} caracteres.')
    text, values = _prepare(expr, ctx)
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError as exc:
        raise ComputeError('A conta tem um erro de escrita (confira parênteses e operadores).') from exc

    def ev(node, raw=False):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return Decimal(str(node.value))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and raw:
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise ComputeError(f'"{node.id}" não é uma variável: use {{{{variavel}}}}.')
            return values[node.id] if raw else to_number(values[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ComputeError('Potência grande demais.')
            if isinstance(node.op, ast.Div) and right == 0:
                raise ComputeError('Divisão por zero.')
            return BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in CMPOPS:
            return Decimal(int(CMPOPS[type(node.ops[0])](ev(node.left), ev(node.comparators[0]))))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            if name in DATE_FUNCS:
                if len(node.args) != 2:
                    raise ComputeError('dias_entre(data1; data2) recebe duas datas.')
                return _dias_entre(ev(node.args[0], raw=True), ev(node.args[1], raw=True))
            if name not in FUNCS or len(node.args) > 20:
                raise ComputeError(f'Função não permitida: {name}. Use: {HELP_FUNCS}.')
            return Decimal(FUNCS[name](*[ev(a) for a in node.args]))
        raise ComputeError('A conta só aceita números, variáveis, + − * / % ( ) e as funções permitidas.')

    try:
        result = ev(tree)
    except (ArithmeticError, TypeError) as exc:
        raise ComputeError('Não foi possível fazer a conta com esses valores.') from exc
    return Decimal(result)


def check_expression(expr: str) -> None:
    """Validação ao salvar a regra: só a forma (as variáveis viram 1 e a data de hoje)."""
    class _Probe(dict):
        pass
    probe_ctx = _Probe()
    for m in VAR.finditer(expr or ''):
        cur = probe_ctx
        parts = m.group(1).split('.')
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = '1'
    try:
        evaluate(expr, probe_ctx)
    except ComputeError as exc:
        if 'data' not in str(exc):                              # datas de verdade só existem na execução
            raise


# ----------------------------------------------------------------------------- tabelas temporárias
def _receivables(org, ctx, client_id):
    from carteira.models import Receivable
    qs = Receivable.objects.filter(organization=org, status=Receivable.Status.OPEN).select_related('contact').order_by('due_date')
    if client_id:
        qs = qs.filter(contact_id=client_id)
    today = timezone.localdate()
    rows = [{'cliente': r.contact.name, 'descricao': r.description, 'vencimento': r.due_date.strftime('%d/%m/%Y'),
             'dias_atraso': max(0, (today - r.due_date).days), 'valor': Decimal(r.amount_cents) / 100} for r in qs[:MAX_ROWS]]
    return ['Cliente', 'Descrição', 'Vencimento', 'Dias de atraso', 'Valor'], rows


def _overdue_receivables(org, ctx, client_id):
    cols, rows = _receivables(org, ctx, client_id)
    return cols, [r for r in rows if r['dias_atraso'] > 0]


def _tasks(org, ctx, client_id):
    from tasks.models import UserTask
    users = org.members.filter(is_active=True).values_list('user_id', flat=True)
    qs = UserTask.objects.filter(responsavel_id__in=users, completed=False).select_related('responsavel').order_by('scheduled_at')
    now = timezone.now()
    rows = [{'tarefa': t.titulo, 'responsavel': t.responsavel.get_full_name() or t.responsavel.email,
             'data': timezone.localtime(t.scheduled_at).strftime('%d/%m/%Y %H:%M'), 'prioridade': t.get_priority_display(),
             'atrasada': 'sim' if t.scheduled_at < now else 'não'} for t in qs[:MAX_ROWS]]
    return ['Tarefa', 'Responsável', 'Data', 'Prioridade', 'Atrasada'], rows


def _deadlines_week(org, ctx, client_id):
    from publications.models import Publication
    today = timezone.localdate()
    qs = Publication.objects.filter(organization=org, vencimento__gte=today, vencimento__lte=today + timedelta(days=7)) \
        .exclude(status='descartada').order_by('vencimento')
    rows = [{'processo': p.cnj or '', 'tribunal': (p.tribunal or '').upper(), 'tipo': p.tipo or '',
             'vencimento': p.vencimento.strftime('%d/%m/%Y'), 'dias': (p.vencimento - today).days} for p in qs[:MAX_ROWS]]
    return ['Processo', 'Tribunal', 'Tipo', 'Vencimento', 'Dias'], rows


def _stale_cases(org, ctx, client_id):
    from research.models import MonitoredCase
    limit = timezone.now() - timedelta(days=60)
    qs = MonitoredCase.objects.filter(organization=org, last_movement_at__lt=limit).select_related('client').order_by('last_movement_at')
    if client_id:
        qs = qs.filter(client_id=client_id)
    rows = [{'processo': c.cnj, 'cliente': c.client.name if c.client_id else '', 'ultimo_andamento':
             timezone.localtime(c.last_movement_at).strftime('%d/%m/%Y'),
             'dias_parado': (timezone.now() - c.last_movement_at).days} for c in qs[:MAX_ROWS]]
    return ['Processo', 'Cliente', 'Último andamento', 'Dias parado'], rows


def _expenses_month(org, ctx, client_id):
    from carteira.models import Expense
    today = timezone.localdate()
    qs = Expense.objects.filter(organization=org, date__year=today.year, date__month=today.month).select_related('contact')
    if client_id:
        qs = qs.filter(contact_id=client_id)
    rows = [{'data': e.date.strftime('%d/%m/%Y'), 'descricao': e.description, 'categoria': e.get_category_display(),
             'cliente': e.contact.name if e.contact_id else '', 'valor': Decimal(e.amount_cents) / 100} for e in qs[:MAX_ROWS]]
    return ['Data', 'Descrição', 'Categoria', 'Cliente', 'Valor'], rows


def _opportunities(org, ctx, client_id):
    from carteira.models import Opportunity
    qs = Opportunity.objects.filter(organization=org).exclude(stage__in=['ganho', 'perdido']).select_related('contact')
    if client_id:
        qs = qs.filter(contact_id=client_id)
    rows = [{'oportunidade': o.title, 'cliente': o.contact.name, 'etapa': o.get_stage_display(), 'area': o.area,
             'valor': Decimal(o.value_cents) / 100} for o in qs.order_by('-updated_at')[:MAX_ROWS]]
    return ['Oportunidade', 'Cliente', 'Etapa', 'Área', 'Valor'], rows


SOURCES = {
    'honorarios_em_aberto': ('Honorários em aberto', _receivables),
    'honorarios_vencidos': ('Honorários vencidos', _overdue_receivables),
    'tarefas_abertas': ('Tarefas não concluídas da equipe', _tasks),
    'prazos_semana': ('Prazos de publicações nos próximos 7 dias', _deadlines_week),
    'processos_parados': ('Processos sem andamento há 60 dias ou mais', _stale_cases),
    'despesas_mes': ('Despesas do mês', _expenses_month),
    'oportunidades_abertas': ('Oportunidades abertas no funil', _opportunities),
}


def build_table(org, ctx: dict, fonte: str, *, do_cliente=False, limite=50) -> dict:
    from automations.engine import resolve
    if fonte not in SOURCES:
        raise ComputeError(f'Fonte de dados desconhecida: {fonte}.')
    client_id = resolve(ctx, 'cliente.id') if do_cliente else None
    if do_cliente and not client_id:
        raise ComputeError('O evento não tem cliente vinculado para filtrar a tabela.')
    cols, rows = SOURCES[fonte][1](org, ctx, client_id)
    rows = rows[:max(1, min(int(limite or 50), MAX_ROWS))]
    total = sum((r['valor'] for r in rows if isinstance(r.get('valor'), Decimal)), Decimal(0))
    keys = list(rows[0].keys()) if rows else []

    def show(v):
        return money(v) if isinstance(v, Decimal) else str(v)
    lines = [' · '.join(show(r[k]) for k in keys if r[k] not in ('', None)) for r in rows[:30]]
    texto = '\n'.join(f'• {line}' for line in lines) + (f'\n… e mais {len(rows) - 30}' if len(rows) > 30 else '')
    return {'quantidade': str(len(rows)), 'total': money(total) if any('valor' in r for r in rows) else '',
            'total_valor': str(total), 'texto': texto or '(nenhum item)', 'colunas': cols,
            'linhas': [[str(r[k]) for k in keys] for r in rows]}              # valores sem "R$": viram número na planilha
