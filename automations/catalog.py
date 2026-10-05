"""O que uma regra pode usar (CAD-172): gatilhos, variáveis de cada gatilho, condições e ações — e a validação do que chega da API.

As variáveis entram nos textos como ``{{processo.cnj}}``. Destinatário de envio é sempre um contato do quadro (com consentimento);
número/e-mail nunca são digitados na regra."""
from __future__ import annotations

from automations.models import Rule

T = Rule.Trigger

COMMON_VARS = {'escritorio.nome': 'Nome do escritório', 'hoje': 'Data de hoje', 'responsavel.nome': 'Responsável'}
TRIGGERS = {
    T.DOCUMENT_CONFIRMED: {
        'label': 'Documento confirmado', 'help': 'Quando alguém (ou a autonomia) confirma a leitura de um documento.',
        'vars': {'documento.nome': 'Nome do arquivo', 'documento.tipo': 'Tipo do documento', 'processo.cnj': 'Nº do processo lido',
                 'prazo.data': 'Data do 1º prazo', 'prazo.descricao': 'Descrição do 1º prazo', 'prazo.fatal': 'Prazo fatal? (sim/não)',
                 'prazos.quantidade': 'Quantos prazos com data', 'resumo': 'Resumo do documento'},
        'destinatarios': []},
    T.CASE_MOVEMENT: {
        'label': 'Andamento novo no processo', 'help': 'Quando o monitoramento encontra andamento novo num processo acompanhado.',
        'vars': {'processo.cnj': 'Nº do processo', 'processo.tribunal': 'Tribunal (ex.: tjsp)', 'processo.apelido': 'Apelido interno',
                 'andamento.nome': 'Andamento mais recente', 'andamento.data': 'Data do andamento', 'andamento.complemento': 'Complemento',
                 'andamentos.quantidade': 'Quantos andamentos novos', 'cliente.nome': 'Cliente do processo',
                 'cliente.primeiro_nome': 'Primeiro nome do cliente'},
        'destinatarios': ['cliente']},
    T.DEADLINE_SOON: {
        'label': 'Prazo chegando', 'help': 'Tarefas de prazo que vencem daqui a N dias úteis (verificado a cada 15 min).',
        'vars': {'tarefa.titulo': 'Título da tarefa', 'prazo.data': 'Data do prazo', 'dias_uteis_restantes': 'Dias úteis até o prazo'},
        'destinatarios': [], 'config': {'dias_antes': 'Dias úteis de antecedência (1 a 30)'}},
    T.CONTACT_CREATED: {
        'label': 'Contato cadastrado', 'help': 'Quando um contato é cadastrado à mão (importações não disparam, para evitar envios em massa).',
        'vars': {'contato.nome': 'Nome', 'contato.primeiro_nome': 'Primeiro nome', 'contato.tipo': 'Tipo (Cliente, Perito…)',
                 'contato.tags': 'Etiquetas'},
        'destinatarios': ['contato']},
    T.PUBLICATION_NEW: {
        'label': 'Publicação nova (DJEN)', 'help': 'Quando a caixa de publicações captura uma comunicação nova (já triada; ainda não confirmada).',
        'vars': {'publicacao.ato': 'Ato (triagem)', 'publicacao.tipo': 'Tipo de comunicação', 'publicacao.tribunal': 'Tribunal',
                 'publicacao.orgao': 'Órgão', 'publicacao.providencia': 'Providência sugerida', 'processo.cnj': 'Nº do processo',
                 'prazo.data': 'Vencimento sugerido', 'prazo.dias': 'Prazo (dias úteis)', 'prazo.fatal': 'Prazo fatal? (sim/não)',
                 'resumo': 'Resumo', 'cliente.nome': 'Cliente do processo', 'cliente.primeiro_nome': 'Primeiro nome do cliente'},
        'destinatarios': ['cliente']},
    T.SCHEDULE: {
        'label': 'Agenda', 'help': 'Todo dia (útil) ou toda semana, a partir da hora escolhida.',
        'vars': {'dia_semana': 'Dia da semana'},
        'destinatarios': [], 'config': {'frequencia': 'diaria | semanal', 'dia_semana': '0=segunda … 6=domingo', 'hora': '0 a 23',
                                        'so_dias_uteis': 'pular feriados/fins de semana'}},
}

OPS = {'eq': 'é igual a', 'neq': 'é diferente de', 'contains': 'contém', 'in': 'é um destes', 'exists': 'está preenchido',
       'not_exists': 'está vazio'}
EXTERNAL = {'send_whatsapp', 'send_email', 'erp_call'}
ACTIONS = {
    'create_task': {'label': 'Criar tarefa', 'externo': False,
                    'params': {'titulo': 'Título (aceita variáveis)', 'descricao': 'Descrição', 'prioridade': 'alta | media | baixa',
                               'quando': 'prazo (data do prazo do evento) | dias_uteis', 'dias': 'Dias úteis a partir de hoje',
                               'antecedencia': 'Dias úteis antes do prazo'}},
    'notify': {'label': 'Avisar a equipe (sino)', 'externo': False, 'params': {'titulo': 'Título', 'mensagem': 'Mensagem'}},
    'send_whatsapp': {'label': 'Enviar WhatsApp ao contato', 'externo': True,
                      'params': {'destinatario': 'cliente | contato', 'mensagem': 'Mensagem'}},
    'send_email': {'label': 'Enviar e-mail ao contato', 'externo': True,
                   'params': {'destinatario': 'cliente | contato', 'assunto': 'Assunto', 'mensagem': 'Mensagem'}},
    'erp_call': {'label': 'Chamar o ERP', 'externo': True,
                 'params': {'conector_id': 'Conector', 'operacao': 'Operação', 'dados': 'Campos (aceitam variáveis)'}},
}
MAX_CONDITIONS, MAX_ACTIONS, MAX_TEXT = 10, 10, 2000


class RuleError(ValueError):
    pass


def catalog() -> dict:
    return {
        'gatilhos': [{'id': k, 'label': v['label'], 'ajuda': v['help'], 'destinatarios': v['destinatarios'], 'config': v.get('config', {}),
                      'variaveis': [{'chave': c, 'label': lbl} for c, lbl in {**v['vars'], **COMMON_VARS}.items()]}
                     for k, v in TRIGGERS.items()],
        'operadores': [{'id': k, 'label': v} for k, v in OPS.items()],
        'acoes': [{'id': k, 'label': v['label'], 'externo': v['externo'], 'params': v['params']} for k, v in ACTIONS.items()],
    }


def _text(params, key, *, required=False, limit=MAX_TEXT) -> str:
    value = params.get(key, '')
    if not isinstance(value, str):
        raise RuleError(f'"{key}" precisa ser texto.')
    value = value.strip()
    if required and not value:
        raise RuleError(f'Preencha "{key}".')
    if len(value) > limit:
        raise RuleError(f'"{key}" passou de {limit} caracteres.')
    return value


def _int(value, key, lo, hi) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise RuleError(f'"{key}" precisa ser um número.') from exc
    if not lo <= n <= hi:
        raise RuleError(f'"{key}" entre {lo} e {hi}.')
    return n


def clean_trigger_config(trigger: str, config) -> dict:
    config = config if isinstance(config, dict) else {}
    if trigger == T.DEADLINE_SOON:
        return {'dias_antes': _int(config.get('dias_antes', 3), 'dias_antes', 1, 30)}
    if trigger == T.SCHEDULE:
        freq = config.get('frequencia', 'diaria')
        if freq not in ('diaria', 'semanal'):
            raise RuleError('Frequência: diaria ou semanal.')
        out = {'frequencia': freq, 'hora': _int(config.get('hora', 8), 'hora', 0, 23), 'so_dias_uteis': bool(config.get('so_dias_uteis', True))}
        if freq == 'semanal':
            out['dia_semana'] = _int(config.get('dia_semana', 0), 'dia_semana', 0, 6)
        return out
    return {}


def clean_conditions(trigger: str, conditions) -> list:
    if conditions in (None, ''):
        return []
    if not isinstance(conditions, list) or len(conditions) > MAX_CONDITIONS:
        raise RuleError(f'Condições: lista com até {MAX_CONDITIONS} itens.')
    allowed = {**TRIGGERS[trigger]['vars'], **COMMON_VARS}
    out = []
    for c in conditions:
        if not isinstance(c, dict):
            raise RuleError('Condição inválida.')
        field, op = c.get('field'), c.get('op')
        if field not in allowed:
            raise RuleError(f'Campo de condição desconhecido para este gatilho: {field}.')
        if op not in OPS:
            raise RuleError(f'Operador desconhecido: {op}.')
        value = c.get('value', '')
        if op == 'in':
            if isinstance(value, str):
                value = [v.strip() for v in value.split(',') if v.strip()]
            if not isinstance(value, list) or not value or len(value) > 50:
                raise RuleError('"é um destes": informe de 1 a 50 valores.')
            value = [str(v)[:200] for v in value]
        elif op in ('exists', 'not_exists'):
            value = ''
        else:
            value = str(value)[:200]
            if not value:
                raise RuleError(f'Informe o valor da condição sobre {field}.')
        out.append({'field': field, 'op': op, 'value': value})
    return out


def clean_actions(trigger: str, actions) -> list:
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise RuleError(f'Escolha de 1 a {MAX_ACTIONS} ações.')
    out = []
    for a in actions:
        if not isinstance(a, dict) or a.get('type') not in ACTIONS:
            raise RuleError(f'Ação desconhecida: {a.get("type") if isinstance(a, dict) else a}.')
        kind, p = a['type'], a.get('params') if isinstance(a.get('params'), dict) else {}
        if kind == 'create_task':
            quando = p.get('quando', 'dias_uteis')
            if quando not in ('prazo', 'dias_uteis'):
                raise RuleError('Tarefa: "quando" deve ser prazo ou dias_uteis.')
            if quando == 'prazo' and trigger not in (T.DOCUMENT_CONFIRMED, T.DEADLINE_SOON, T.PUBLICATION_NEW):
                raise RuleError('Este gatilho não traz data de prazo: use "dias_uteis".')
            prioridade = p.get('prioridade', 'media')
            if prioridade not in ('alta', 'media', 'baixa'):
                raise RuleError('Prioridade: alta, media ou baixa.')
            params = {'titulo': _text(p, 'titulo', required=True, limit=255), 'descricao': _text(p, 'descricao'),
                      'prioridade': prioridade, 'quando': quando}
            if quando == 'prazo':
                params['antecedencia'] = _int(p.get('antecedencia', 0), 'antecedencia', 0, 30)
            else:
                params['dias'] = _int(p.get('dias', 0), 'dias', 0, 60)
        elif kind == 'notify':
            params = {'titulo': _text(p, 'titulo', required=True, limit=120), 'mensagem': _text(p, 'mensagem', required=True, limit=500)}
        elif kind in ('send_whatsapp', 'send_email'):
            dest = p.get('destinatario')
            if dest not in TRIGGERS[trigger]['destinatarios']:
                options = ', '.join(TRIGGERS[trigger]['destinatarios']) or 'nenhum (este gatilho não tem contato vinculado)'
                raise RuleError(f'Destinatário inválido para este gatilho. Opções: {options}.')
            params = {'destinatario': dest, 'mensagem': _text(p, 'mensagem', required=True, limit=1000)}
            if kind == 'send_email':
                params['assunto'] = _text(p, 'assunto', required=True, limit=150)
        else:   # erp_call
            dados = p.get('dados') or {}
            if not isinstance(dados, dict) or len(dados) > 30 or not all(isinstance(v, str) and len(v) <= 500 for v in dados.values()):
                raise RuleError('ERP: "dados" deve ser um objeto com até 30 campos de texto.')
            params = {'conector_id': _int(p.get('conector_id'), 'conector_id', 1, 2**31), 'operacao': _text(p, 'operacao', required=True, limit=60),
                      'dados': {str(k)[:60]: v for k, v in dados.items()}}
        out.append({'type': kind, 'params': params})
    return out


def clean_rule(data: dict, *, partial_of: Rule | None = None) -> dict:
    """Valida o corpo da API. ``partial_of``: PATCH (campos ausentes ficam como estão)."""
    base = partial_of
    trigger = data.get('trigger', base.trigger if base else None)
    if trigger not in TRIGGERS:
        raise RuleError('Escolha o gatilho.')
    out = {'trigger': trigger}
    if 'name' in data or base is None:
        name = str(data.get('name') or '').strip()
        if not 3 <= len(name) <= 120:
            raise RuleError('Nome entre 3 e 120 caracteres.')
        out['name'] = name
    if 'description' in data:
        out['description'] = str(data.get('description') or '').strip()[:500]
    trigger_changed = base is not None and trigger != base.trigger
    for key, fn, default in (('trigger_config', clean_trigger_config, {}), ('conditions', clean_conditions, []),
                             ('actions', clean_actions, None)):
        if key in data or base is None or trigger_changed:
            value = data.get(key, getattr(base, key) if base else default)
            out[key] = fn(trigger, value)
    if 'require_approval' in data:
        out['require_approval'] = data['require_approval'] is not False
    return out
