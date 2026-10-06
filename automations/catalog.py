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
    T.RECEIVABLE_DUE: {
        'label': 'Honorário vencendo ou vencido', 'help': 'Régua de cobrança: lançamentos em aberto que vencem daqui a N dias '
                                                          'ou que venceram há N dias (verificado a cada 15 min).',
        'vars': {'honorario.descricao': 'Descrição do lançamento', 'honorario.valor': 'Valor (R$)', 'honorario.vencimento': 'Vencimento',
                 'honorario.link_pagamento': 'Link de pagamento (Asaas)', 'honorario.dias_atraso': 'Dias de atraso',
                 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome do cliente'},
        'destinatarios': ['cliente'], 'config': {'quando': 'antes | vencido', 'dias': 'Dias (0 a 60)'}},
    T.EMAIL_RECEIVED: {
        'label': 'E-mail recebido (triado)', 'help': 'Quando chega e-mail numa caixa conectada. O Cadrius classifica (intimação, cliente, '
                                                    'agenda, financeiro, comercial…) e você filtra pela categoria nas condições.',
        'vars': {'email.assunto': 'Assunto', 'email.remetente': 'Remetente', 'email.categoria': 'Categoria (intimacao, cliente, agenda…)',
                 'email.urgencia': 'Urgência (alta, media, baixa)', 'email.resumo': 'Resumo', 'email.acao_sugerida': 'Ação sugerida',
                 'prazo.data': 'Data citada no e-mail', 'contato.nome': 'Contato que enviou (se cadastrado)',
                 'contato.primeiro_nome': 'Primeiro nome do contato'},
        'destinatarios': ['contato']},
    T.CALENDAR_EVENT: {
        'label': 'Compromisso da Agenda Google chegando', 'help': 'Prazos, audiências e reuniões criados direto no Google Agenda, N dias '
                                                                 'antes (verificado a cada 15 min, a partir das 8h).',
        'vars': {'evento.titulo': 'Título', 'evento.tipo': 'Tipo (prazo, audiencia, reuniao, pericia, outro)', 'evento.data': 'Data',
                 'evento.hora': 'Hora', 'evento.local': 'Local', 'dias_restantes': 'Dias até o compromisso', 'processo.cnj': 'Processo citado',
                 'cliente.nome': 'Cliente vinculado', 'cliente.primeiro_nome': 'Primeiro nome do cliente'},
        'destinatarios': ['cliente'], 'config': {'dias_antes': 'Dias de antecedência (0 a 30)'}},
    T.TASK_OVERDUE: {
        'label': 'Tarefa atrasada', 'help': 'Tarefa não concluída que passou do horário há N dias (verificado a cada 15 min).',
        'vars': {'tarefa.titulo': 'Título', 'tarefa.prioridade': 'Prioridade', 'tarefa.data': 'Data prevista', 'dias_atraso': 'Dias de atraso'},
        'destinatarios': [], 'config': {'dias_atraso': 'Dias de atraso (0 a 30)'}},
    T.RECEIVABLE_PAID: {
        'label': 'Pagamento recebido', 'help': 'Quando um honorário recebe baixa (à mão ou pelo Asaas).',
        'vars': {'honorario.descricao': 'Descrição', 'honorario.valor': 'Valor pago (R$)', 'honorario.data_pagamento': 'Data do pagamento',
                 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome do cliente'},
        'destinatarios': ['cliente']},
    T.OPPORTUNITY_STAGE: {
        'label': 'Oportunidade mudou de etapa', 'help': 'Funil da Carteira: ex. "Reunião marcada" envia confirmação, "Não fechou" pede retorno.',
        'vars': {'oportunidade.titulo': 'Título', 'oportunidade.etapa': 'Etapa nova (novo, qualificacao, reuniao, proposta, ganho, perdido)',
                 'oportunidade.etapa_anterior': 'Etapa anterior', 'oportunidade.area': 'Área', 'oportunidade.proxima_acao': 'Próxima ação',
                 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome do cliente'},
        'destinatarios': ['cliente']},
    T.AGREEMENT_CREATED: {
        'label': 'Contrato de honorários criado', 'help': 'Boas-vindas ao cliente, tarefa de abertura do caso, aviso ao financeiro…',
        'vars': {'contrato.titulo': 'Título', 'contrato.tipo': 'Tipo', 'contrato.valor': 'Valor total (R$)', 'contrato.parcelas': 'Parcelas',
                 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome do cliente'},
        'destinatarios': ['cliente']},
    T.DOCUMENT_UPLOADED: {
        'label': 'Documento enviado', 'help': 'Assim que um arquivo é enviado (antes da leitura pela IA).',
        'vars': {'documento.nome': 'Nome do arquivo', 'documento.tipo': 'Tipo informado', 'documento.cliente': 'Cliente informado no envio'},
        'destinatarios': []},
    T.PORTAL_VIEWED: {
        'label': 'Cliente abriu o portal', 'help': 'No máximo um aviso por hora por cliente.',
        'vars': {'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome', 'portal.acessos': 'Acessos até agora'},
        'destinatarios': []},
    # ---------------------------------------------------------------- CAD-223
    T.LEAD_CAPTURED: {
        'label': 'Contato pelo formulário de captação', 'help': 'Alguém preencheu o formulário do site: vira oportunidade "Novo contato".',
        'vars': {'oportunidade.titulo': 'Título', 'oportunidade.area': 'Assunto escolhido', 'formulario.titulo': 'Formulário',
                 'campanha.nome': 'Campanha', 'cliente.nome': 'Nome', 'cliente.primeiro_nome': 'Primeiro nome',
                 'consentimento.whatsapp': 'Autorizou WhatsApp? (sim/não)', 'consentimento.email': 'Autorizou e-mail? (sim/não)'},
        'destinatarios': ['cliente']},
    T.SURVEY_ANSWERED: {
        'label': 'Cliente respondeu a pesquisa de satisfação', 'help': 'Nota de 0 a 10 (NPS). Detrator = 0 a 6; neutro = 7 e 8; promotor = 9 e 10.',
        'vars': {'pesquisa.nota': 'Nota (0 a 10)', 'pesquisa.classificacao': 'promotor | neutro | detrator', 'pesquisa.motivo': 'Motivo do envio',
                 'pesquisa.tem_comentario': 'Deixou comentário? (sim/não)', 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome'},
        'destinatarios': ['cliente']},
    T.NFSE_ISSUED: {
        'label': 'Nota fiscal de honorários emitida', 'help': 'A prefeitura autorizou a NFS-e pedida pelo Cadrius (via Asaas).',
        'vars': {'honorario.descricao': 'Descrição', 'honorario.valor': 'Valor (R$)', 'nota.link': 'Link da nota (PDF)',
                 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome'},
        'destinatarios': ['cliente']},
    T.EXPENSE_CREATED: {
        'label': 'Despesa lançada', 'help': 'Inclui as despesas fixas lançadas sozinhas todo mês. Use condições (ex.: categoria).',
        'vars': {'despesa.descricao': 'Descrição', 'despesa.categoria': 'Categoria (custas, diligencia, pericia, escritorio…)',
                 'despesa.valor': 'Valor (R$)', 'despesa.valor_centavos': 'Valor em centavos (para comparar)',
                 'despesa.reembolsavel': 'Cliente reembolsa? (sim/não)', 'cliente.nome': 'Cliente vinculado'},
        'destinatarios': ['cliente']},
    T.COURT_SUSPENSION: {
        'label': 'Suspensão de prazos no tribunal', 'help': 'A Cadrius cadastrou suspensão/indisponibilidade num tribunal onde o '
                                                           'escritório tem processo. A contagem de prazos do Cadrius já considera.',
        'vars': {'suspensao.tribunal': 'Tribunal', 'suspensao.tipo': 'Tipo', 'suspensao.inicio': 'Início', 'suspensao.fim': 'Fim',
                 'suspensao.motivo': 'Motivo', 'suspensao.fonte': 'Link do ato oficial', 'processos.quantidade': 'Processos do escritório ali'},
        'destinatarios': []},
    T.CONTACT_BIRTHDAY: {
        'label': 'Aniversário do cliente', 'help': 'No dia do aniversário (dia e mês do cadastro), a partir das 9h.',
        'vars': {'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome'},
        'destinatarios': ['cliente']},
    T.OPPORTUNITY_STALE: {
        'label': 'Oportunidade parada no funil', 'help': 'Oportunidade aberta que não muda de etapa há N dias.',
        'vars': {'oportunidade.titulo': 'Título', 'oportunidade.etapa': 'Etapa', 'oportunidade.dias_parada': 'Dias sem mudar',
                 'oportunidade.proxima_acao': 'Próxima ação', 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome'},
        'destinatarios': ['cliente'], 'config': {'dias': 'Dias sem mudar de etapa (3 a 90)'}},
    T.CASE_STALE: {
        'label': 'Processo sem andamento', 'help': 'Processo acompanhado sem andamento novo há N dias (bom para cobrar o cartório/'
                                                   'secretaria ou dar notícia ao cliente).',
        'vars': {'processo.cnj': 'Nº do processo', 'processo.tribunal': 'Tribunal', 'processo.apelido': 'Apelido',
                 'processo.ultimo_andamento': 'Data do último andamento', 'processo.dias_parado': 'Dias sem andamento',
                 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome'},
        'destinatarios': ['cliente'], 'config': {'dias': 'Dias sem andamento (15 a 365)'}},
    T.CONTRACT_ENDING: {
        'label': 'Contrato de honorários terminando', 'help': 'A última parcela em aberto vence em N dias (renovação, fechamento do caso).',
        'vars': {'contrato.titulo': 'Título', 'contrato.tipo': 'Tipo', 'contrato.ultima_parcela': 'Vencimento da última parcela',
                 'cliente.nome': 'Cliente', 'cliente.primeiro_nome': 'Primeiro nome'},
        'destinatarios': ['cliente'], 'config': {'dias': 'Dias antes da última parcela (1 a 60)'}},
    T.MONTHLY_GOAL: {
        'label': 'Acompanhamento da meta do mês', 'help': 'No dia escolhido do mês, às 9h: quanto da meta de faturamento já entrou.',
        'vars': {'meta.valor': 'Meta (R$)', 'meta.recebido': 'Recebido no mês (R$)', 'meta.pct': '% da meta',
                 'meta.previsto': 'Ainda previsto no mês (R$)', 'meta.atingida': 'Meta atingida? (sim/não)'},
        'destinatarios': [], 'config': {'dia': 'Dia do mês (1 a 28)'}},
    T.SCHEDULE: {
        'label': 'Agenda', 'help': 'Todo dia (útil) ou toda semana, a partir da hora escolhida.',
        'vars': {'dia_semana': 'Dia da semana'},
        'destinatarios': [], 'config': {'frequencia': 'diaria | semanal', 'dia_semana': '0=segunda … 6=domingo', 'hora': '0 a 23',
                                        'so_dias_uteis': 'pular feriados/fins de semana'}},
}

OPS = {'eq': 'é igual a', 'neq': 'é diferente de', 'contains': 'contém', 'in': 'é um destes', 'exists': 'está preenchido',
       'not_exists': 'está vazio'}
EXTERNAL = {'send_whatsapp', 'send_email', 'send_message', 'erp_call', 'team_chat', 'send_survey'}
ACTIONS = {
    'create_task': {'label': 'Criar tarefa', 'externo': False,
                    'params': {'titulo': 'Título (aceita variáveis)', 'descricao': 'Descrição', 'prioridade': 'alta | media | baixa',
                               'quando': 'prazo (data do prazo do evento) | dias_uteis', 'dias': 'Dias úteis a partir de hoje',
                               'antecedencia': 'Dias úteis antes do prazo'}},
    'notify': {'label': 'Avisar a equipe (sino)', 'externo': False, 'params': {'titulo': 'Título', 'mensagem': 'Mensagem'}},
    'send_whatsapp': {'label': 'Enviar WhatsApp ao contato', 'externo': True,
                      'params': {'destinatario': 'cliente | contato', 'mensagem': 'Mensagem'}},
    'send_message': {'label': 'Avisar o cliente (melhor canal autorizado)', 'externo': True,
                     'params': {'destinatario': 'cliente | contato', 'canal': 'melhor | whatsapp | email', 'assunto': 'Assunto (e-mail)',
                                'mensagem': 'Mensagem'}},
    'send_email': {'label': 'Enviar e-mail ao contato', 'externo': True,
                   'params': {'destinatario': 'cliente | contato', 'assunto': 'Assunto', 'mensagem': 'Mensagem'}},
    'send_survey': {'label': 'Pedir avaliação ao cliente (pesquisa de satisfação)', 'externo': True,
                    'params': {'destinatario': 'cliente', 'canal': 'melhor | whatsapp | email', 'motivo': 'Motivo (ex.: Contrato concluído)',
                               'mensagem': 'Mensagem (o link da pesquisa entra no fim)'}},
    'team_chat': {'label': 'Avisar no chat da equipe (Slack, Teams ou Telegram)', 'externo': True,
                  'params': {'canal': 'slack | teams | telegram', 'mensagem': 'Mensagem (aceita variáveis)'}},
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
    if trigger == T.CALENDAR_EVENT:
        return {'dias_antes': _int(config.get('dias_antes', 1), 'dias_antes', 0, 30)}
    if trigger == T.TASK_OVERDUE:
        return {'dias_atraso': _int(config.get('dias_atraso', 1), 'dias_atraso', 0, 30)}
    if trigger == T.OPPORTUNITY_STALE:
        return {'dias': _int(config.get('dias', 7), 'dias', 3, 90)}
    if trigger == T.CASE_STALE:
        return {'dias': _int(config.get('dias', 60), 'dias', 15, 365)}
    if trigger == T.CONTRACT_ENDING:
        return {'dias': _int(config.get('dias', 15), 'dias', 1, 60)}
    if trigger == T.MONTHLY_GOAL:
        return {'dia': _int(config.get('dia', 20), 'dia', 1, 28)}
    if trigger == T.SCHEDULE:
        freq = config.get('frequencia', 'diaria')
        if freq not in ('diaria', 'semanal'):
            raise RuleError('Frequência: diaria ou semanal.')
        out = {'frequencia': freq, 'hora': _int(config.get('hora', 8), 'hora', 0, 23), 'so_dias_uteis': bool(config.get('so_dias_uteis', True))}
        if freq == 'semanal':
            out['dia_semana'] = _int(config.get('dia_semana', 0), 'dia_semana', 0, 6)
        return out
    if trigger == T.RECEIVABLE_DUE:
        when = config.get('quando', 'antes')
        if when not in ('antes', 'vencido'):
            raise RuleError('Quando: antes (do vencimento) ou vencido.')
        return {'quando': when, 'dias': _int(config.get('dias', 3), 'dias', 0, 60)}
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
            if quando == 'prazo' and trigger not in (T.DOCUMENT_CONFIRMED, T.DEADLINE_SOON, T.PUBLICATION_NEW, T.CALENDAR_EVENT,
                                                     T.EMAIL_RECEIVED, T.TASK_OVERDUE):
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
        elif kind in ('send_whatsapp', 'send_email', 'send_message'):
            dest = p.get('destinatario')
            if dest not in TRIGGERS[trigger]['destinatarios']:
                options = ', '.join(TRIGGERS[trigger]['destinatarios']) or 'nenhum (este gatilho não tem contato vinculado)'
                raise RuleError(f'Destinatário inválido para este gatilho. Opções: {options}.')
            params = {'destinatario': dest, 'mensagem': _text(p, 'mensagem', required=True, limit=1000)}
            if kind == 'send_email':
                params['assunto'] = _text(p, 'assunto', required=True, limit=150)
            if kind == 'send_message':
                canal = p.get('canal', 'melhor')
                if canal not in ('melhor', 'whatsapp', 'email'):
                    raise RuleError('Canal: melhor, whatsapp ou email.')
                params.update(canal=canal, assunto=_text(p, 'assunto', limit=150))
        elif kind == 'send_survey':
            if 'cliente' not in TRIGGERS[trigger]['destinatarios']:
                raise RuleError('Este gatilho não tem cliente vinculado para receber a pesquisa.')
            canal = p.get('canal', 'melhor')
            if canal not in ('melhor', 'whatsapp', 'email'):
                raise RuleError('Canal: melhor, whatsapp ou email.')
            params = {'destinatario': 'cliente', 'canal': canal, 'motivo': _text(p, 'motivo', limit=120),
                      'mensagem': _text(p, 'mensagem', required=True, limit=800)}
        elif kind == 'team_chat':
            canal = p.get('canal')
            if canal not in ('slack', 'teams', 'telegram'):
                raise RuleError('Canal: slack, teams ou telegram.')
            params = {'canal': canal, 'mensagem': _text(p, 'mensagem', required=True, limit=1000)}
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
