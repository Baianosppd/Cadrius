GET /api/v1/funcionarios/
Dropdown de responsavel
[
  {
    "user_id": "",
    "name": "",
    "email": "",
    "role": ""
  }
]

POST /api/v1/tasks/
Criar tarefa (prioridade: alta, media, baixa; responsavel = user_id de /funcionarios/)
{
  "titulo": "",
  "descricao": "",
  "dataHorario": "",
  "prioridade": "",
  "responsavel": "",
  "sincronizar": false
}

GET /api/v1/documentos/?nome=&page=1&page_size=10
Listar documentos paginado (nome vazio = todos; cliente null = sem vinculo)
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 0,
      "nome": "",
      "cliente": null,
      "tipo": "",
      "data": "",
      "status": ""
    }
  ]
}

POST /api/v1/documentos/
Criar documento, multipart/form-data (tipo: contrato, peticao, procuracao, outro; status: processando, pronto, aguardando_assinatura, assinado)
{
  "nome": "",
  "tipo": "",
  "status": "",
  "arquivo": ""
}

POST /api/v1/documentos/cliente/
Criar documento vinculado a nome do cliente, multipart/form-data (mesmos valores de tipo e status)
{
  "nome": "",
  "tipo": "",
  "status": "",
  "arquivo": "",
  "nome_cliente": ""
}

GET /api/v1/documentos/{id}/download/
Download do arquivo do documento

GET /api/v1/teams/members/
Listar membros da equipe com creditos do mes (creditos_limite null = sem cota individual)
[
  {
    "id": "",
    "email": "",
    "first_name": "",
    "last_name": "",
    "role": "",
    "status": "ativo",
    "creditos_usados": 0,
    "creditos_limite": null,
    "joined_at": ""
  }
]

PATCH /api/v1/teams/members/{id}/credits/
Definir cota mensal do membro (so owner/admin; null remove a cota)
{
  "creditos_limite": 0
}

GET /api/v1/teams/credits/
Creditos gerais do escritorio no mes
{
  "creditos_total": 0,
  "creditos_usados": 0,
  "creditos_disponiveis": 0,
  "creditos_distribuidos": 0,
  "creditos_nao_distribuidos": 0
}

GET /api/billing/plans/current/
Plano atual do escritorio e outros planos (proxima_cobranca null = sem data)
{
  "plano": {
    "id": 0,
    "name": "",
    "price": "",
    "description": "",
    "features": []
  },
  "status": "ativo",
  "proxima_cobranca": "",
  "outros_planos": [
    {
      "id": 0,
      "name": "",
      "price": "",
      "description": "",
      "features": []
    }
  ]
}

GET /api/v1/notifications/?page=1&page_size=20
Listar notificacoes do usuario, mais recentes primeiro (type: documento, prazo, automacao, erro)
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 0,
      "title": "",
      "description": "",
      "time": "",
      "read": false,
      "type": "",
      "origem": "",
      "documento": "",
      "acao": "",
      "detalhes": "",
      "actionLabel": "",
      "link": "",
      "created_at": ""
    }
  ]
}

GET /api/v1/notifications/unread-count/
Numero do sino (consultar a cada 42s)
{
  "unread": 0
}

POST /api/v1/notifications/{id}/read/
Marcar uma notificacao como lida (devolve a notificacao)

POST /api/v1/notifications/read-all/
Marcar todas como lidas (sem body; JSON abaixo e a resposta)
{
  "updated": 0
}

GET /api/v1/sync-history/?page=1&page_size=20
Historico de sincronizacao com integracoes externas (status: sucesso, falha)
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 0,
      "title": "",
      "description": "",
      "time": "",
      "status": "",
      "integration": "",
      "created_at": ""
    }
  ]
}

POST /api/v1/auth/register/
Cadastro pessoa fisica, sem token (oab_numero, oab_uf e area_atuacao opcionais; area_atuacao: civil, penal, trabalhista, tributario, empresarial, familia, previdenciario, outra)
{
  "nome_completo": "",
  "cpf": "",
  "email": "",
  "senha": "",
  "oab_numero": "",
  "oab_uf": "",
  "area_atuacao": "",
  "plano_id": 0
}

POST /api/v1/auth/register/empresa/
Cadastro empresa, sem token (tipo_sociedade: LTDA, SA, EIRELI, MEI, opcional; porte_empresa: MEI, ME, EPP, GRANDE_PORTE; regime_tributario: SIMPLES_NACIONAL, LUCRO_PRESUMIDO, LUCRO_REAL, opcional; endereco e cargo opcionais)
{
  "razao_social": "",
  "nome_fantasia": "",
  "cnpj": "",
  "tipo_sociedade": "",
  "porte_empresa": "",
  "regime_tributario": "",
  "cep": "",
  "logradouro": "",
  "numero": "",
  "bairro": "",
  "cidade": "",
  "uf": "",
  "telefone_principal": "",
  "email_corporativo": "",
  "gerente": {
    "nome_completo": "",
    "cpf": "",
    "email": "",
    "senha": "",
    "cargo": ""
  },
  "plano_id": 0
}

Resposta 201 dos dois cadastros (ja loga o usuario)
{
  "user": {
    "id": "",
    "email": "",
    "nome_completo": ""
  },
  "organization": {
    "id": "",
    "name": "",
    "account_type": "",
    "plano_id": 0
  },
  "access": "",
  "refresh": ""
}
