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
    # ---------------------------------------------------------------- CAD-222: agenda Google, e-mails, funil, contratos
    'agenda_audiencia_cliente': {
        'name': 'Lembrar o cliente da audiência (1 dia antes)',
        'description': 'Audiência marcada no Google Agenda: avisa o cliente pelo melhor canal que ele autorizou (WhatsApp ou e-mail), '
                       'em horário comercial e depois de alguém aprovar o texto.',
        'trigger': 'calendar_event', 'trigger_config': {'dias_antes': 1},
        'conditions': [{'field': 'evento.tipo', 'op': 'eq', 'value': 'audiencia'}],
        'actions': [{'type': 'send_message', 'params': {
            'destinatario': 'cliente', 'canal': 'melhor', 'assunto': 'Lembrete: audiência em {{evento.data}}',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}! Lembrete da sua audiência em {{evento.data}} às {{evento.hora}} '
                        '({{evento.local}}). Chegue com 30 minutos de antecedência e leve documento com foto. Qualquer dúvida, '
                        'fale com {{escritorio.nome}}.'}}],
    },
    'agenda_prazo_equipe': {
        'name': 'Prazo do Google Agenda: aviso à equipe 2 dias antes',
        'description': 'Prazos lançados direto no Google Agenda também entram no radar: aviso no sino 2 dias antes.',
        'trigger': 'calendar_event', 'trigger_config': {'dias_antes': 2},
        'conditions': [{'field': 'evento.tipo', 'op': 'eq', 'value': 'prazo'}],
        'actions': [{'type': 'notify', 'params': {'titulo': 'Prazo em 2 dias: {{evento.titulo}}',
                                                  'mensagem': 'Vence em {{evento.data}}. Processo {{processo.cnj}}.'}}],
    },
    'email_intimacao_tarefa': {
        'name': 'E-mail de intimação vira tarefa urgente',
        'description': 'E-mail classificado como intimação/tribunal: tarefa para hoje e aviso no sino.',
        'trigger': 'email_received', 'trigger_config': {},
        'conditions': [{'field': 'email.categoria', 'op': 'eq', 'value': 'intimacao'}],
        'actions': [
            {'type': 'create_task', 'params': {'titulo': 'Intimação por e-mail: {{email.assunto}}', 'descricao': '{{email.resumo}}',
                                               'prioridade': 'alta', 'quando': 'dias_uteis', 'dias': 0}},
            {'type': 'notify', 'params': {'titulo': 'Intimação recebida por e-mail', 'mensagem': '{{email.assunto}} — {{email.acao_sugerida}}'}},
        ],
    },
    'email_cliente_responder': {
        'name': 'Mensagem de cliente: tarefa para responder em 1 dia útil',
        'description': 'Nenhum cliente fica sem resposta: e-mail de cliente cadastrado vira tarefa.',
        'trigger': 'email_received', 'trigger_config': {},
        'conditions': [{'field': 'email.categoria', 'op': 'eq', 'value': 'cliente'}],
        'actions': [{'type': 'create_task', 'params': {'titulo': 'Responder {{contato.nome}}: {{email.assunto}}',
                                                       'descricao': '{{email.resumo}}', 'prioridade': 'media',
                                                       'quando': 'dias_uteis', 'dias': 1}}],
    },
    'email_comercial_aviso': {
        'name': 'Possível cliente novo por e-mail: avisar a equipe',
        'description': 'Pedido de orçamento/consulta: aviso imediato para não perder o lead.',
        'trigger': 'email_received', 'trigger_config': {},
        'conditions': [{'field': 'email.categoria', 'op': 'eq', 'value': 'comercial'}],
        'actions': [{'type': 'notify', 'params': {'titulo': 'Possível cliente novo', 'mensagem': '{{email.remetente}}: {{email.assunto}}'}},
                    {'type': 'create_task', 'params': {'titulo': 'Retornar contato comercial: {{email.remetente}}',
                                                       'descricao': '{{email.resumo}}', 'prioridade': 'alta',
                                                       'quando': 'dias_uteis', 'dias': 0}}],
    },
    'pagamento_agradecimento': {
        'name': 'Agradecer o pagamento',
        'description': 'Confirma ao cliente que o pagamento foi recebido.',
        'trigger': 'receivable_paid', 'trigger_config': {}, 'conditions': [],
        'actions': [{'type': 'send_message', 'params': {
            'destinatario': 'cliente', 'canal': 'melhor', 'assunto': 'Pagamento recebido',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}! Confirmamos o recebimento de {{honorario.valor}} ({{honorario.descricao}}). '
                        'Obrigado! {{escritorio.nome}}'}}],
    },
    'funil_reuniao_confirmacao': {
        'name': 'Confirmar a reunião com o possível cliente',
        'description': 'Quando a oportunidade vai para "Reunião marcada", envia a confirmação.',
        'trigger': 'opportunity_stage', 'trigger_config': {},
        'conditions': [{'field': 'oportunidade.etapa', 'op': 'eq', 'value': 'reuniao'}],
        'actions': [{'type': 'send_message', 'params': {
            'destinatario': 'cliente', 'canal': 'melhor', 'assunto': 'Reunião confirmada',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}! Sua reunião com {{escritorio.nome}} está confirmada: '
                        '{{oportunidade.proxima_acao}}. Traga os documentos que tiver sobre o caso.'}}],
    },
    'contrato_boas_vindas': {
        'name': 'Boas-vindas e abertura do caso ao fechar contrato',
        'description': 'Mensagem de boas-vindas ao cliente e tarefa para abrir a pasta do caso.',
        'trigger': 'agreement_created', 'trigger_config': {}, 'conditions': [],
        'actions': [
            {'type': 'send_message', 'params': {
                'destinatario': 'cliente', 'canal': 'melhor', 'assunto': 'Bem-vindo(a) ao {{escritorio.nome}}',
                'mensagem': 'Olá, {{cliente.primeiro_nome}}! Seja bem-vindo(a). Seu contrato "{{contrato.titulo}}" foi registrado. '
                            'Vamos te manter informado(a) por aqui sobre cada passo.'}},
            {'type': 'create_task', 'params': {'titulo': 'Abrir o caso: {{contrato.titulo}}', 'descricao': 'Cliente {{cliente.nome}}.',
                                               'prioridade': 'media', 'quando': 'dias_uteis', 'dias': 1}},
        ],
    },
    'tarefa_atrasada_aviso': {
        'name': 'Tarefa atrasada há 1 dia: avisar',
        'description': 'Aviso no sino de tarefas que passaram do horário e não foram concluídas.',
        'trigger': 'task_overdue', 'trigger_config': {'dias_atraso': 1}, 'conditions': [],
        'actions': [{'type': 'notify', 'params': {'titulo': 'Tarefa atrasada', 'mensagem': '{{tarefa.titulo}} (prevista para {{tarefa.data}}).'}}],
    },
    # ---------------------------------------------------------------- CAD-223
    'lead_responder': {
        'name': 'Responder quem preencheu o formulário',
        'description': 'Contato novo pelo formulário vira tarefa para responder no mesmo dia útil e avisa a equipe.',
        'trigger': 'lead_captured', 'trigger_config': {}, 'conditions': [],
        'actions': [{'type': 'create_task', 'params': {'titulo': 'Responder {{cliente.nome}} ({{oportunidade.area}})',
                                                        'descricao': 'Contato pelo formulário "{{formulario.titulo}}".', 'prioridade': 'alta',
                                                        'quando': 'dias_uteis', 'dias': 0}},
                    {'type': 'notify', 'params': {'titulo': 'Novo contato pelo formulário', 'mensagem': '{{cliente.nome}} — {{oportunidade.area}}'}}],
    },
    'pesquisa_contrato_concluido': {
        'name': 'Pedir avaliação no fim do contrato',
        'description': 'Um dia antes da última parcela do contrato, envia a pesquisa de satisfação (nota de 0 a 10).',
        'trigger': 'contract_ending', 'trigger_config': {'dias': 1}, 'conditions': [],
        'actions': [{'type': 'send_survey', 'params': {
            'destinatario': 'cliente', 'canal': 'melhor', 'motivo': 'Contrato concluído',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}! Sua opinião nos ajuda a melhorar. Pode responder em 1 minuto?'}}],
    },
    'detrator_ligar': {
        'name': 'Cliente insatisfeito: ligar',
        'description': 'Nota de 0 a 6 na pesquisa cria tarefa urgente para o responsável ligar.',
        'trigger': 'survey_answered', 'trigger_config': {},
        'conditions': [{'field': 'pesquisa.classificacao', 'op': 'eq', 'value': 'detrator'}],
        'actions': [{'type': 'create_task', 'params': {'titulo': 'Ligar para {{cliente.nome}} (nota {{pesquisa.nota}})', 'descricao': '',
                                                        'prioridade': 'alta', 'quando': 'dias_uteis', 'dias': 1}}],
    },
    'nota_enviar_cliente': {
        'name': 'Enviar a nota fiscal ao cliente',
        'description': 'Quando a prefeitura autoriza a NFS-e, manda o link ao cliente.',
        'trigger': 'nfse_issued', 'trigger_config': {}, 'conditions': [],
        'actions': [{'type': 'send_message', 'params': {
            'destinatario': 'cliente', 'canal': 'email', 'assunto': 'Nota fiscal dos honorários',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}! Segue a nota fiscal de {{honorario.descricao}} ({{honorario.valor}}): {{nota.link}}'}}],
    },
    'custas_reembolso': {
        'name': 'Avisar o financeiro de custas reembolsáveis',
        'description': 'Despesa reembolsável lançada avisa o financeiro para cobrar o cliente.',
        'trigger': 'expense_created', 'trigger_config': {},
        'conditions': [{'field': 'despesa.reembolsavel', 'op': 'eq', 'value': 'sim'}],
        'actions': [{'type': 'notify', 'params': {'titulo': 'Despesa reembolsável: {{despesa.valor}}',
                                                  'mensagem': '{{despesa.descricao}} — cliente {{cliente.nome}}.'}}],
    },
    'suspensao_prazos_equipe': {
        'name': 'Avisar a equipe de suspensão de prazos',
        'description': 'O tribunal suspendeu prazos (cadastrado pela Cadrius): aviso no sino com o link oficial.',
        'trigger': 'court_suspension', 'trigger_config': {}, 'conditions': [],
        'actions': [{'type': 'notify', 'params': {'titulo': '{{suspensao.tipo}} — {{suspensao.tribunal}}',
                                                  'mensagem': 'De {{suspensao.inicio}} a {{suspensao.fim}}: {{suspensao.motivo}}. '
                                                              '{{processos.quantidade}} processo(s) do escritório. Fonte: {{suspensao.fonte}}'}}],
    },
    'aniversario_cliente': {
        'name': 'Parabéns no aniversário do cliente',
        'description': 'Mensagem cordial no dia do aniversário (só para quem autorizou o canal).',
        'trigger': 'contact_birthday', 'trigger_config': {}, 'conditions': [],
        'actions': [{'type': 'send_message', 'params': {
            'destinatario': 'cliente', 'canal': 'melhor', 'assunto': 'Feliz aniversário',
            'mensagem': 'Olá, {{cliente.primeiro_nome}}! A equipe de {{escritorio.nome}} deseja um feliz aniversário.'}}],
    },
    'funil_parado': {
        'name': 'Retomar oportunidade parada',
        'description': 'Oportunidade sem mudar de etapa há 7 dias vira tarefa de retorno.',
        'trigger': 'opportunity_stale', 'trigger_config': {'dias': 7}, 'conditions': [],
        'actions': [{'type': 'create_task', 'params': {'titulo': 'Retomar: {{oportunidade.titulo}} ({{oportunidade.dias_parada}} dias)',
                                                        'descricao': 'Próxima ação: {{oportunidade.proxima_acao}}', 'prioridade': 'media',
                                                        'quando': 'dias_uteis', 'dias': 0}}],
    },
    'processo_parado': {
        'name': 'Processo parado: verificar no cartório',
        'description': 'Sem andamento há 60 dias: tarefa para consultar a secretaria (Balcão Virtual) e dar notícia ao cliente.',
        'trigger': 'case_stale', 'trigger_config': {'dias': 60}, 'conditions': [],
        'actions': [{'type': 'create_task', 'params': {'titulo': 'Verificar andamento: {{processo.cnj}}',
                                                        'descricao': 'Sem andamento há {{processo.dias_parado}} dias. Consulte a secretaria '
                                                                     '(Balcão Virtual) e atualize o cliente.',
                                                        'prioridade': 'media', 'quando': 'dias_uteis', 'dias': 1}}],
    },
    'meta_mes_equipe': {
        'name': 'Meta do mês no dia 20',
        'description': 'No dia 20, avisa quanto da meta de faturamento já entrou.',
        'trigger': 'monthly_goal', 'trigger_config': {'dia': 20}, 'conditions': [],
        'actions': [{'type': 'notify', 'params': {'titulo': 'Meta do mês: {{meta.pct}}%',
                                                  'mensagem': 'Recebido {{meta.recebido}} de {{meta.valor}}; ainda previsto {{meta.previsto}}.'}}],
    },

}


def listing() -> list:
    return [{'key': k, 'name': t['name'], 'description': t['description'], 'trigger': t['trigger'],
             'actions': [a['type'] for a in t['actions']]} for k, t in TEMPLATES.items()]
