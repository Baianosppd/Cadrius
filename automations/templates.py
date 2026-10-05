"""Modelos prontos de regra (CAD-172). Criar a partir de um modelo gera a regra DESLIGADA: o escritório revisa, simula e liga."""
from __future__ import annotations

TEMPLATES = {
    'andamento_avisa_cliente': {
        'name': 'Avisar o cliente sobre andamento novo',
        'description': 'Manda WhatsApp ao cliente do processo (só com consentimento) depois que alguém da equipe aprova o texto.',
        'trigger': 'case_movement', 'trigger_config': {}, 'conditions': [],
        'actions': [{'type': 'send_whatsapp', 'params': {
            'destinatario': 'cliente',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}! Houve uma movimentação no seu processo {{processo.cnj}}: '
                        '{{andamento.nome}} ({{andamento.data}}). Qualquer dúvida, fale com {{escritorio.nome}}.'}}],
    },
    'andamento_cria_tarefa': {
        'name': 'Tarefa para analisar cada andamento novo',
        'description': 'Cria uma tarefa para o responsável do processo analisar o andamento em até 2 dias úteis.',
        'trigger': 'case_movement', 'trigger_config': {}, 'conditions': [],
        'actions': [{'type': 'create_task', 'params': {
            'titulo': 'Analisar andamento: {{andamento.nome}}', 'descricao': 'Processo {{processo.cnj}} ({{processo.tribunal}}).',
            'prioridade': 'media', 'quando': 'dias_uteis', 'dias': 2}}],
    },
    'prazo_lembrete': {
        'name': 'Lembrete de prazo 3 dias úteis antes',
        'description': 'Avisa a equipe no sino quando uma tarefa de prazo vence em 3 dias úteis.',
        'trigger': 'deadline_soon', 'trigger_config': {'dias_antes': 3}, 'conditions': [],
        'actions': [{'type': 'notify', 'params': {
            'titulo': 'Prazo em {{dias_uteis_restantes}} dias úteis', 'mensagem': '{{tarefa.titulo}} vence em {{prazo.data}}.'}}],
    },
    'documento_prazo_fatal': {
        'name': 'Prazo fatal em documento: revisão no dia anterior',
        'description': 'Quando um documento confirmado tem prazo fatal, cria a tarefa de revisão 1 dia útil antes e avisa a equipe.',
        'trigger': 'document_confirmed', 'trigger_config': {},
        'conditions': [{'field': 'prazo.fatal', 'op': 'eq', 'value': 'sim'}],
        'actions': [
            {'type': 'create_task', 'params': {'titulo': 'Revisar peça: {{prazo.descricao}}', 'descricao': 'Documento: {{documento.nome}}.',
                                               'prioridade': 'alta', 'quando': 'prazo', 'antecedencia': 1}},
            {'type': 'notify', 'params': {'titulo': 'Prazo fatal identificado', 'mensagem': '{{prazo.descricao}} em {{prazo.data}} ({{documento.nome}}).'}},
        ],
    },
    'cliente_boas_vindas': {
        'name': 'Boas-vindas ao cliente novo',
        'description': 'Envia um e-mail de boas-vindas quando um contato do tipo Cliente é cadastrado (só com consentimento por e-mail).',
        'trigger': 'contact_created', 'trigger_config': {},
        'conditions': [{'field': 'contato.tipo', 'op': 'eq', 'value': 'Cliente'}],
        'actions': [{'type': 'send_email', 'params': {
            'destinatario': 'contato', 'assunto': 'Bem-vindo(a) ao {{escritorio.nome}}',
            'mensagem': 'Olá, {{contato.primeiro_nome}}!\n\nObrigado pela confiança. A partir de agora acompanharemos seu caso '
                        'e avisaremos sobre as novidades.\n\n{{escritorio.nome}}'}}],
    },
    'publicacao_prazo_fatal': {
        'name': 'Publicação com prazo fatal: preparar a peça 2 dias úteis antes',
        'description': 'Quando chega publicação com prazo fatal, cria a tarefa de preparar a peça 2 dias úteis antes do vencimento '
                       'sugerido e avisa a equipe (a confirmação da publicação continua na caixa).',
        'trigger': 'publication_new', 'trigger_config': {},
        'conditions': [{'field': 'prazo.fatal', 'op': 'eq', 'value': 'sim'}],
        'actions': [
            {'type': 'create_task', 'params': {'titulo': 'Preparar: {{publicacao.ato}} — {{processo.cnj}}',
                                               'descricao': '{{publicacao.providencia}} Vencimento sugerido: {{prazo.data}}.',
                                               'prioridade': 'alta', 'quando': 'prazo', 'antecedencia': 2}},
            {'type': 'notify', 'params': {'titulo': 'Publicação com prazo fatal', 'mensagem': '{{publicacao.ato}} em {{processo.cnj}} '
                                                                                              '({{publicacao.tribunal}}): vence {{prazo.data}}.'}},
        ],
    },
    'regua_lembrete': {
        'name': 'Régua de cobrança: lembrete 3 dias antes do vencimento',
        'description': 'Três dias antes do vencimento, manda ao cliente um e-mail cordial com o valor e o link de pagamento '
                       '(só com consentimento por e-mail; passa por aprovação).',
        'trigger': 'receivable_due', 'trigger_config': {'quando': 'antes', 'dias': 3},
        'conditions': [],
        'actions': [{'type': 'send_email', 'params': {
            'destinatario': 'cliente', 'assunto': 'Lembrete: honorários vencem em {{honorario.vencimento}}',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}!\n\nLembramos que "{{honorario.descricao}}", no valor de {{honorario.valor}}, '
                        'vence em {{honorario.vencimento}}.\n{{honorario.link_pagamento}}\n\nSe já pagou, desconsidere.\n\n'
                        '{{escritorio.nome}}'}}],
    },
    'regua_vencido': {
        'name': 'Régua de cobrança: honorário vencido há 5 dias',
        'description': 'Cinco dias após o vencimento sem pagamento, avisa a equipe e cria a tarefa de contato com o cliente.',
        'trigger': 'receivable_due', 'trigger_config': {'quando': 'vencido', 'dias': 5},
        'conditions': [],
        'actions': [
            {'type': 'notify', 'params': {'titulo': 'Honorário vencido', 'mensagem': '{{cliente.nome}}: {{honorario.descricao}} '
                                                                                     '({{honorario.valor}}) venceu em {{honorario.vencimento}}.'}},
            {'type': 'create_task', 'params': {'titulo': 'Falar com {{cliente.nome}} sobre honorário vencido',
                                               'descricao': '{{honorario.descricao}} — {{honorario.valor}}, vencido há {{honorario.dias_atraso}} dias.',
                                               'prioridade': 'media', 'quando': 'dias_uteis', 'dias': 0}}],
    },
    'semanal_revisao': {
        'name': 'Revisão semanal da carteira',
        'description': 'Toda segunda às 8h, cria a tarefa de revisar prazos e processos da semana.',
        'trigger': 'schedule', 'trigger_config': {'frequencia': 'semanal', 'dia_semana': 0, 'hora': 8, 'so_dias_uteis': True},
        'conditions': [],
        'actions': [{'type': 'create_task', 'params': {'titulo': 'Revisão semanal de prazos e processos',
                                                       'descricao': 'Semana de {{hoje}}.', 'prioridade': 'media',
                                                       'quando': 'dias_uteis', 'dias': 0}}],
    },
}


def listing() -> list:
    return [{'key': k, 'name': t['name'], 'description': t['description'], 'trigger': t['trigger'],
             'actions': [a['type'] for a in t['actions']]} for k, t in TEMPLATES.items()]
