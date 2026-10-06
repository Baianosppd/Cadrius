"""Ferramentas do assistente (CAD-221).

- LEITURA: rodam na hora, sempre restritas ao escritório da pessoa.
- AÇÃO: a IA só PROPÕE (vira ``PendingAction``); quem executa é a pessoa, ao confirmar — e com as permissões do perfil dela.

Texto vindo de terceiros (publicação, documento) volta para a IA delimitado como NÃO CONFIÁVEL (``wrap_untrusted``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable

from django.utils import timezone

WRITE_ROLES = {'OWNER', 'ADMIN', 'MEMBER'}


class ToolError(Exception):
    """Erro com mensagem segura para devolver à IA e à pessoa."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable
    action: bool = False           # True = muda dados → precisa de confirmação
    label: str = ''                # como aparece para a pessoa

    def spec(self) -> dict:
        return {'name': self.name, 'description': self.description, 'parameters': self.parameters}


def _obj(props: dict, required=()) -> dict:
    return {'type': 'object', 'properties': props, 'required': list(required), 'additionalProperties': False}


S = {'type': 'string'}
INT = {'type': 'integer'}


def _date(value, field='data') -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ToolError(f'{field} inválida: use AAAA-MM-DD.') from exc


def _untrusted(text: str, limit=4000) -> str:
    from aigov.sanitize import wrap_untrusted
    return wrap_untrusted((text or '')[:limit])


def _brl(cents) -> str:
    from carteira.services import brl
    return brl(int(cents or 0))


# ----------------------------------------------------------------------------- leitura
def buscar_contatos(ctx, termo: str = '', tipo: str = ''):
    from contacts.api import search
    from contacts.models import Contact
    qs = Contact.objects.filter(organization=ctx.org)
    if tipo in Contact.Kind.values:
        qs = qs.filter(kind=tipo)
    rows = list(search(qs, termo))[:10] if termo else list(qs.order_by('-created_at')[:10])
    return [{'id': c.pk, 'nome': c.name, 'tipo': c.get_kind_display(), 'email': c.email, 'telefone': c.phone,
             'pode_whatsapp': c.can_receive('whatsapp'), 'pode_email': c.can_receive('email'), 'link': f'/contatos?abrir={c.pk}'}
            for c in rows]


def buscar_processos(ctx, termo: str = ''):
    from core.pii import blind_index
    from research.models import MonitoredCase
    qs = MonitoredCase.objects.filter(organization=ctx.org, is_active=True).select_related('client')
    digits = re.sub(r'\D', '', termo or '')
    if len(digits) == 20:
        qs = qs.filter(cnj_bidx=blind_index('case.cnj', digits, 'digits'))
        rows = list(qs[:10])
    else:
        t = (termo or '').casefold()
        rows = [c for c in qs.order_by('-last_movement_at')[:300]
                if not t or t in f'{c.cnj} {c.label} {c.client.name if c.client else ""}'.casefold()
                or (digits and digits in re.sub(r'\D', '', c.cnj))][:10]
    out = []
    for c in rows:
        last = c.movements.order_by('-occurred_at').first()
        out.append({'id': c.pk, 'cnj': c.cnj, 'tribunal': c.tribunal.upper(), 'apelido': c.label,
                    'cliente': c.client.name if c.client else '', 'ultimo_andamento': last.name if last else '',
                    'data_ultimo_andamento': last.occurred_at.date().isoformat() if last and last.occurred_at else '',
                    'link': '/acompanhamento'})
    return out


def publicacoes(ctx, status: str = 'nova', dias: int = 30):
    from publications.models import Publication
    since = timezone.localdate() - timedelta(days=max(1, min(int(dias or 30), 180)))
    qs = Publication.objects.filter(organization=ctx.org, disponibilizada_em__gte=since)
    if status in Publication.Status.values:
        qs = qs.filter(status=status)
    return [{'id': p.pk, 'tribunal': p.tribunal, 'tipo': p.tipo, 'processo': p.cnj, 'disponibilizada_em': p.disponibilizada_em.isoformat(),
             'vencimento': p.vencimento.isoformat() if p.vencimento else '', 'status': p.get_status_display(),
             'resumo_ia': (p.triage or {}).get('resumo', ''), 'providencia': (p.triage or {}).get('providencia', ''),
             'link': '/publicacoes'} for p in qs.order_by('vencimento', '-disponibilizada_em')[:15]]


def ler_publicacao(ctx, id: int):
    from publications.models import Publication
    p = Publication.objects.filter(organization=ctx.org, pk=id).first()
    if not p:
        raise ToolError('Publicação não encontrada neste escritório.')
    return {'id': p.pk, 'processo': p.cnj, 'tribunal': p.tribunal, 'orgao': p.orgao, 'tipo': p.tipo,
            'vencimento': p.vencimento.isoformat() if p.vencimento else '', 'texto': _untrusted(p.texto, 6000)}


def agenda(ctx, dias: int = 7):
    from publications.models import Publication
    from tasks.models import UserTask
    today = timezone.localdate()
    until = today + timedelta(days=max(1, min(int(dias or 7), 60)))
    prazos = Publication.objects.filter(organization=ctx.org, vencimento__gte=today, vencimento__lte=until) \
        .exclude(status='descartada').order_by('vencimento')[:20]
    tarefas = UserTask.objects.filter(responsavel=ctx.user, completed=False,
                                      scheduled_at__date__lte=until).order_by('scheduled_at')[:20]
    return {'hoje': today.isoformat(),
            'prazos': [{'publicacao_id': p.pk, 'processo': p.cnj, 'vencimento': p.vencimento.isoformat(),
                        'providencia': (p.triage or {}).get('providencia', ''), 'status': p.get_status_display()} for p in prazos],
            'tarefas': [{'titulo': t.titulo, 'quando': timezone.localtime(t.scheduled_at).strftime('%Y-%m-%d %H:%M'),
                         'prioridade': t.get_priority_display(), 'atrasada': t.scheduled_at.date() < today} for t in tarefas]}


def buscar_documentos(ctx, termo: str = ''):
    from documents.models import Document
    qs = Document.objects.filter(organization=ctx.org)
    if termo:
        qs = qs.filter(nome__icontains=termo[:80])
    return [{'id': d.pk, 'nome': d.nome, 'tipo': d.tipo, 'status': d.status, 'data': d.data.date().isoformat(),
             'link': f'/documents/{d.pk}'} for d in qs.order_by('-data')[:10]]


def calcular_prazo(ctx, data_inicio: str, dias_uteis: int, tribunal: str = '', disponibilizacao: bool = False):
    from forense.calendar import Calendar
    try:
        r = Calendar(ctx.org, (tribunal or '').lower()).count(_date(data_inicio, 'data_inicio'), int(dias_uteis),
                                                              from_availability=bool(disponibilizacao))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return {'vencimento': r['vencimento'].isoformat(), 'publicacao': r['publicacao'].isoformat() if r['publicacao'] else '',
            'dias_uteis': r['dias_uteis'], 'dias_pulados': [{'data': s['data'].isoformat(), 'motivo': s['motivo']} for s in r['pulados']],
            'aviso': 'Contagem em dias úteis (CPC art. 219 e 224) com feriados nacionais, recesso e feriados cadastrados pelo escritório. '
                     'Confira feriados locais do tribunal.'}


def resumo_financeiro(ctx, dias: int = 30):
    if ctx.role not in {'OWNER', 'ADMIN'}:
        raise ToolError('Só dono ou administrador do escritório veem o financeiro.')
    from carteira.services import summary
    end = timezone.localdate()
    s = summary(ctx.org, end - timedelta(days=max(1, min(int(dias or 30), 365))), end)
    return {'a_receber': _brl(s['a_receber_centavos']), 'vencido': _brl(s['vencido_centavos']), 'parcelas_vencidas': s['vencidos'],
            'inadimplencia_pct': s['inadimplencia_pct'], 'previsto_30_dias': _brl(s['previsto_30_dias_centavos']),
            'recebido_no_periodo': _brl(s['recebido_centavos']), 'despesas_no_periodo': _brl(s['despesas_centavos']),
            'resultado': _brl(s['resultado_centavos']), 'link': '/financas'}


def memoria_do_escritorio(ctx, consulta: str):
    from brain import memory
    found = memory.similar(ctx.org, consulta[:1000], k=4)
    return [{'tipo': item.get_kind_display(), 'titulo': item.title, 'conteudo': _untrusted(item.text, 1200)}
            for _score, item in found]


# ----------------------------------------------------------------------------- ações (só com confirmação)
def criar_tarefa(ctx, titulo: str, data: str, hora: str = '09:00', descricao: str = '', prioridade: str = 'media'):
    from tasks.models import UserTask
    day = _date(data)
    try:
        hh, mm = (int(x) for x in (hora or '09:00').split(':')[:2])
        when = timezone.make_aware(datetime.combine(day, time(hh, mm)))
    except (ValueError, TypeError) as exc:
        raise ToolError('Hora inválida: use HH:MM.') from exc
    if prioridade not in UserTask.Priority.values:
        prioridade = 'media'
    t = UserTask.objects.create(titulo=titulo[:255], descricao=descricao[:2000], scheduled_at=when, priority=prioridade,
                                responsavel=ctx.user)
    return {'id': t.pk, 'mensagem': f'Tarefa "{t.titulo}" criada para {day.strftime("%d/%m/%Y")} às {hh:02d}:{mm:02d}.', 'link': '/dashboard'}


def criar_contato(ctx, nome: str, tipo: str = 'cliente', email: str = '', telefone: str = '', documento: str = ''):
    from audit import service as audit
    from contacts.api import duplicate_email
    from contacts.models import Contact
    from contacts.validation import clean_contact
    values, errors = clean_contact({'name': nome, 'kind': tipo, 'email': email, 'phone': telefone, 'document': documento})
    if errors:
        raise ToolError(' '.join(errors))
    if duplicate_email(ctx.org, values.get('email')):
        raise ToolError('Já existe um contato com este e-mail.')
    c = Contact.objects.create(organization=ctx.org, created_by=ctx.user, **values)
    audit.log('contact.created', actor=ctx.user, organization=ctx.org, target=c, changes={'kind': c.kind, 'origem': 'assistente'},
              data_categories=['identificacao', 'contato'], legal_basis='execucao_contrato')
    return {'id': c.pk, 'mensagem': f'Contato "{c.name}" cadastrado.', 'link': f'/contatos?abrir={c.pk}'}


def gerar_minuta(ctx, modelo: str, publicacao_id: int | None = None, titulo: str = '', usar_ia: bool = False):
    from minutas import services
    key = modelo if ':' in (modelo or '') else f'builtin:{modelo}'
    try:
        draft = services.generate(ctx.org, ctx.user, template_key=key, source_type='publicacao' if publicacao_id else '',
                                  source_id=publicacao_id, use_ai=bool(usar_ia), title=titulo)
    except services.DraftError as exc:
        raise ToolError(str(exc) or 'Modelo de minuta inválido.') from exc
    return {'id': draft.pk, 'mensagem': f'Minuta "{draft.title}" criada como rascunho para revisão.', 'link': f'/minutas?abrir={draft.pk}'}


def lancar_despesa(ctx, descricao: str, valor: str, data: str = '', categoria: str = 'custas', reembolsavel: bool = False,
                   contato_id: int | None = None):
    from carteira.services import FinanceError, create_expense, to_cents
    from contacts.models import Contact
    contact = Contact.objects.filter(organization=ctx.org, pk=contato_id).first() if contato_id else None
    try:
        exp = create_expense(ctx.org, ctx.user, description=descricao, category=categoria, amount_cents=to_cents(valor),
                             when=_date(data) if data else timezone.localdate(), contact=contact, reimbursable=bool(reembolsavel))
    except FinanceError as exc:
        raise ToolError(str(exc)) from exc
    return {'id': exp.pk, 'mensagem': f'Despesa "{exp.description}" de {_brl(exp.amount_cents)} lançada.', 'link': '/financas'}


def marcar_publicacao_revisada(ctx, id: int, nota: str = ''):
    from publications.models import Publication
    p = Publication.objects.filter(organization=ctx.org, pk=id).first()
    if not p:
        raise ToolError('Publicação não encontrada neste escritório.')
    p.status, p.reviewed_by, p.reviewed_at, p.review_note = 'confirmada', ctx.user, timezone.now(), (nota or '')[:255]
    p.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])
    from audit import service as audit
    audit.log('publication.reviewed', actor=ctx.user, organization=ctx.org, target=p, changes={'status': p.status, 'origem': 'assistente'})
    return {'id': p.pk, 'mensagem': 'Publicação marcada como revisada.', 'link': '/publicacoes'}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool('buscar_contatos', 'Procura clientes e demais contatos do escritório por nome, e-mail, telefone ou CPF/CNPJ.',
         _obj({'termo': S, 'tipo': {'type': 'string', 'enum': ['', 'cliente', 'parte_contraria', 'testemunha', 'perito',
                                                                 'correspondente', 'fornecedor', 'outro']}}), buscar_contatos,
         label='Busca de contatos'),
    Tool('buscar_processos', 'Procura processos acompanhados pelo número CNJ, apelido ou nome do cliente; traz o último andamento.',
         _obj({'termo': S}), buscar_processos, label='Busca de processos'),
    Tool('publicacoes', 'Lista publicações do Diário (DJEN) do escritório. status: nova, confirmada, descartada (ou vazio para todas).',
         _obj({'status': S, 'dias': INT}), publicacoes, label='Publicações'),
    Tool('ler_publicacao', 'Lê o texto completo de uma publicação pelo id.', _obj({'id': INT}, ['id']), ler_publicacao,
         label='Leitura de publicação'),
    Tool('agenda', 'Prazos (vencimentos de publicações) e tarefas da pessoa nos próximos dias.', _obj({'dias': INT}), agenda,
         label='Agenda'),
    Tool('buscar_documentos', 'Procura documentos enviados ao escritório pelo nome do arquivo.', _obj({'termo': S}), buscar_documentos,
         label='Busca de documentos'),
    Tool('calcular_prazo', 'Calcula vencimento em dias úteis (CPC) com feriados e recesso. data_inicio = intimação ou disponibilização '
         '(AAAA-MM-DD); disponibilizacao=true quando a data é a disponibilização no Diário eletrônico.',
         _obj({'data_inicio': S, 'dias_uteis': INT, 'tribunal': S, 'disponibilizacao': {'type': 'boolean'}}, ['data_inicio', 'dias_uteis']),
         calcular_prazo, label='Cálculo de prazo'),
    Tool('resumo_financeiro', 'Resumo financeiro do escritório (a receber, vencido, recebido, despesas). Só para dono/administrador.',
         _obj({'dias': INT}), resumo_financeiro, label='Resumo financeiro'),
    Tool('memoria_do_escritorio', 'Consulta o que o escritório já ensinou ao Cadrius (exemplos aprovados, preferências e estilo).',
         _obj({'consulta': S}, ['consulta']), memoria_do_escritorio, label='Memória do escritório'),
    Tool('criar_tarefa', 'PROPÕE criar uma tarefa para a pessoa (precisa de confirmação). data AAAA-MM-DD, hora HH:MM, '
         'prioridade alta|media|baixa.', _obj({'titulo': S, 'data': S, 'hora': S, 'descricao': S, 'prioridade': S}, ['titulo', 'data']),
         criar_tarefa, action=True, label='Criar tarefa'),
    Tool('criar_contato', 'PROPÕE cadastrar um contato (precisa de confirmação).',
         _obj({'nome': S, 'tipo': S, 'email': S, 'telefone': S, 'documento': S}, ['nome']), criar_contato, action=True,
         label='Cadastrar contato'),
    Tool('gerar_minuta', 'PROPÕE gerar uma minuta a partir de um modelo (resposta_cliente, peticao_juntada, manifestacao_ciencia, '
         'notificacao_extrajudicial ou modelo do escritório), opcionalmente ligada a uma publicação. usar_ia=true reescreve com IA '
         '(consome mais créditos).', _obj({'modelo': S, 'publicacao_id': INT, 'titulo': S, 'usar_ia': {'type': 'boolean'}}, ['modelo']),
         gerar_minuta, action=True, label='Gerar minuta'),
    Tool('lancar_despesa', 'PROPÕE lançar despesa/custas (valor em reais, ex.: "250,00"; categoria custas|diligencia|pericia|'
         'deslocamento|copias|escritorio|outros).',
         _obj({'descricao': S, 'valor': S, 'data': S, 'categoria': S, 'reembolsavel': {'type': 'boolean'}, 'contato_id': INT},
              ['descricao', 'valor']), lancar_despesa, action=True, label='Lançar despesa'),
    Tool('marcar_publicacao_revisada', 'PROPÕE marcar uma publicação como revisada/confirmada.', _obj({'id': INT, 'nota': S}, ['id']),
         marcar_publicacao_revisada, action=True, label='Revisar publicação'),
]}


def describe(tool: Tool, args: dict) -> str:
    """Resumo legível do que será feito (mostrado no cartão de confirmação)."""
    shown = ', '.join(f'{k}: {v}' for k, v in args.items() if v not in ('', None))
    return f'{tool.label}' + (f' — {shown}' if shown else '')
