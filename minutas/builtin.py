"""Modelos de minuta do Cadrius (CAD-173). Variáveis entre chaves duplas; o que faltar vira ``[COMPLETAR: …]``.

São pontos de partida genéricos — cada escritório pode cadastrar os próprios modelos (Minutas → Modelos)."""

VARS = {
    'escritorio.nome': 'Nome do escritório', 'advogado.nome': 'Advogado(a)', 'advogado.oab': 'OAB do advogado(a)', 'hoje': 'Data por extenso',
    'cidade': 'Cidade', 'processo.cnj': 'Nº do processo', 'processo.tribunal': 'Tribunal', 'processo.orgao': 'Vara/órgão',
    'processo.classe': 'Classe', 'cliente.nome': 'Cliente', 'parte_contraria.nome': 'Parte contrária', 'ato': 'Ato (sentença, despacho…)',
    'prazo.dias': 'Prazo (dias úteis)', 'prazo.data': 'Vencimento', 'providencia': 'Providência', 'resumo': 'Resumo da fonte',
    'documento.nome': 'Documento de origem', 'fonte.data': 'Data da fonte', 'assinatura': 'Assinatura padrão do escritório',
}

BUILTIN = {
    'resposta_cliente': {
        'name': 'Comunicado ao cliente sobre a movimentação', 'kind': 'comunicado',
        'body': (
            'Prezado(a) {{cliente.nome}},\n\n'
            'Informamos que no processo nº {{processo.cnj}} ({{processo.tribunal}}) houve a seguinte movimentação em {{fonte.data}}: '
            '{{ato}}.\n\n'
            'Em resumo: {{resumo}}\n\n'
            'Próximo passo: {{providencia}} O prazo vence em {{prazo.data}}. Manteremos você informado(a).\n\n'
            'Ficamos à disposição para qualquer dúvida.\n\n'
            'Atenciosamente,\n{{advogado.nome}}\n{{escritorio.nome}}'),
    },
    'peticao_juntada': {
        'name': 'Petição de juntada de documento', 'kind': 'peticao',
        'body': (
            'EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA {{processo.orgao}}\n\n'
            'Processo nº {{processo.cnj}}\n\n'
            '{{cliente.nome}}, já qualificado(a) nos autos da ação em epígrafe movida em face de {{parte_contraria.nome}}, por seu(sua) '
            'advogado(a) que esta subscreve, vem, respeitosamente, à presença de Vossa Excelência requerer a juntada do documento '
            '"{{documento.nome}}", para os fins de direito.\n\n'
            'Termos em que,\npede deferimento.\n\n{{cidade}}, {{hoje}}.\n\n{{advogado.nome}}\nOAB {{advogado.oab}}'),
    },
    'manifestacao_ciencia': {
        'name': 'Manifestação de ciência / cumprimento', 'kind': 'peticao',
        'body': (
            'EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA {{processo.orgao}}\n\n'
            'Processo nº {{processo.cnj}}\n\n'
            '{{cliente.nome}}, nos autos em epígrafe, por seu(sua) advogado(a), vem, respeitosamente, em atenção à intimação '
            'disponibilizada em {{fonte.data}} ({{ato}}), manifestar ciência e informar que [COMPLETAR: providência adotada].\n\n'
            'Termos em que,\npede deferimento.\n\n{{cidade}}, {{hoje}}.\n\n{{advogado.nome}}\nOAB {{advogado.oab}}'),
    },
    'notificacao_extrajudicial': {
        'name': 'Notificação extrajudicial', 'kind': 'notificacao',
        'body': (
            'NOTIFICAÇÃO EXTRAJUDICIAL\n\n'
            'Notificante: {{cliente.nome}}\nNotificado(a): {{parte_contraria.nome}}\n\n'
            'Pela presente, {{cliente.nome}}, por meio de seu(sua) advogado(a), NOTIFICA Vossa Senhoria acerca de [COMPLETAR: fatos], '
            'conforme {{documento.nome}}, para que, no prazo de [COMPLETAR: prazo] dias contados do recebimento desta, '
            '[COMPLETAR: providência exigida], sob pena de adoção das medidas judiciais cabíveis.\n\n'
            '{{cidade}}, {{hoje}}.\n\n{{advogado.nome}}\nOAB {{advogado.oab}}\n{{escritorio.nome}}'),
    },
}
