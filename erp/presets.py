"""Modelos prontos de ERP jurídico. **[VALIDAR]** Nenhum endpoint abaixo foi confirmado contra a documentação/contrato do fornecedor:
são um ponto de partida. Como as operações são DADOS (``ErpConnector.operations``), o escritório/a equipe corrige caminhos e campos
sem novo deploy. Ver docs/CONECTOR_ERP.md.

Operação: ``method``, ``path`` (relativo, com ``{param}``), ``body`` (``"$.campo"`` lê da entrada; qualquer outro valor é constante),
``query`` (idem), ``required`` (campos da entrada), ``mutating`` (altera dados no ERP → exige confirmação humana).
"""
PRESETS = {
    'PROJURIS': {
        'label': 'Projuris (modelo — validar com o fornecedor)',
        'auth': {'type': 'bearer'},                       # credenciais: {"token": "..."}
        'base_url_hint': 'https://<sua-conta>.projuris.com.br/api',
        'operations': {
            'ping': {'method': 'GET', 'path': '/v1/ping', 'mutating': False, 'required': []},
            'buscar_processo': {'method': 'GET', 'path': '/v1/processos', 'query': {'numero': '$.cnj'},
                                'mutating': False, 'required': ['cnj']},
            'registrar_andamento': {'method': 'POST', 'path': '/v1/processos/{processo_id}/andamentos',
                                    'body': {'descricao': '$.texto', 'data': '$.data'},
                                    'mutating': True, 'required': ['processo_id', 'texto']},
            'criar_tarefa': {'method': 'POST', 'path': '/v1/tarefas',
                             'body': {'titulo': '$.titulo', 'descricao': '$.descricao', 'vencimento': '$.vencimento',
                                      'processoId': '$.processo_id'},
                             'mutating': True, 'required': ['titulo']},
        },
    },
    'CUSTOM': {
        'label': 'ERP personalizado (você define as operações)',
        'auth': {'type': 'bearer'},
        'base_url_hint': 'https://erp.exemplo.com/api',
        'operations': {},
    },
}
