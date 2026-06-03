# Catálogo de Endpoints — API Cadrius

Documento de referência dos endpoints HTTP da API REST do Cadrius. O intercâmbio de dados utiliza JSON; a autenticação padrão é JWT via header `Authorization: Bearer <access_token>`, exceto nas rotas públicas indicadas.

**Base URL (desenvolvimento):** `http://localhost:8000`  
**Listagens paginadas:** `{ count, next, previous, results[] }` — 10 itens por página  
**Documentação OpenAPI:** `/api/docs/` · `/api/schema/`

**Valores de `action_type`:** `WEBHOOK` · `WHATSAPP_EVOLUTION` · `EMAIL_SMTP` (e-mail ainda não executado pelo worker)

---

## Rotas WEBHOOK — entrada pública (sem JWT)

Endpoints invocados por sistemas externos. Não utilizam JWT; a autenticação, quando existente, é própria do provedor.

| Rota | Origem típica | Efeito |
|------|---------------|--------|
| **`POST /api/workflows/webhooks/catch/{token}/`** | CRM, formulários, ERPs | Dispara automação associada ao `webhook_token` |
| **`POST /api/workflows/webhook/inbound/{connection_id}/`** | Evolution API (WhatsApp) | Recebe eventos inbound |
| **`POST /api/webhooks/receive/{connection_id}/`** | Integrações via `AppConnection` | Enfileira workflows ligados à conexão |
| **`POST /api/billing/webhook/`** | Stripe | Processa eventos de pagamento |

> **`action_type: WEBHOOK`** numa automação refere-se à **saída** (Cadrius invoca URL externa). As rotas acima são de **entrada**.

---

## Infraestrutura

### `GET /healthz/`
- **Descrição:** Verificação de disponibilidade da API e conectividade com o banco de dados.
- **Auth:** nenhuma
- **Response 200:**
```json
{ "status": "ok", "db_status": "ok", "app_version": "v1.0.0" }
```

---

## Autenticação

### `POST /api/v1/auth/token/` — Login
- **Descrição:** Autenticação de utilizador e emissão de par de tokens JWT. O campo `username` corresponde ao e-mail.
- **Auth:** nenhuma
- **Request:**
```json
{ "username": "user@email.com", "password": "senha123" }
```
- **Response 200:**
```json
{ "refresh": "<jwt>", "access": "<jwt>" }
```

### `POST /api/v1/auth/token/refresh/`
- **Descrição:** Renovação do token de acesso a partir do refresh token.
- **Auth:** nenhuma
- **Request:**
```json
{ "refresh": "<jwt_refresh>" }
```
- **Response 200:**
```json
{ "access": "<jwt>" }
```

### `POST /api/v1/auth/register/` — Cadastro
- **Descrição:** Registo de novo utilizador na plataforma.
- **Auth:** nenhuma
- **Request:**
```json
{
  "email": "novo@email.com",
  "password": "senha123",
  "first_name": "João",
  "last_name": "Silva"
}
```
- **Response 201:**
```json
{
  "id": "uuid",
  "email": "novo@email.com",
  "first_name": "João",
  "last_name": "Silva"
}
```
- **Erro 400:** `{ "email": ["Este e-mail já está sendo usado."] }`

### `GET /api/v1/auth/user/` — Perfil
- **Descrição:** Consulta dos dados do utilizador autenticado.
- **Auth:** JWT
- **Response 200:**
```json
{
  "id": "uuid",
  "email": "user@email.com",
  "first_name": "João",
  "last_name": "Silva",
  "initials": "JS"
}
```

---

## Dashboard

### `GET /api/v1/dashboard/stats/`
- **Descrição:** Indicadores agregados do painel (parcialmente mock).
- **Auth:** JWT
- **Response 200:**
```json
{
  "automacoes_ativas": 0,
  "processos_ativos": 0,
  "prazos_hoje": 0,
  "tempo_economizado": "0h"
}
```

---

## Mailboxes (IMAP)

### `POST /api/v1/mailboxes/`
- **Descrição:** Registo de caixa IMAP para captura periódica de e-mails (intervalo de 5 minutos).
- **Auth:** JWT
- **Request:**
```json
{
  "name": "Caixa Jurídica",
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "username": "teste@gmail.com",
  "is_active": true
}
```
- **Response 201:** campos acima + `id`, `last_fetch_at`, `user`

### `PUT / PATCH /api/v1/mailboxes/{id}/`
- **Descrição:** Atualização de caixa IMAP.
- **Auth:** JWT
- **Request / Response:** mesmos campos do POST

### `GET /api/v1/mailboxes/` · `GET .../{id}/` · `DELETE .../{id}/`
- **Descrição:** Listagem, consulta e remoção (`204`).

---

## E-mails capturados

### `GET /api/v1/emails/` · `GET /api/v1/emails/{id}/`
- **Descrição:** Listagem e detalhe de mensagens capturadas. Parâmetro opcional `?q=` filtra assunto e remetente.
- **Auth:** JWT
- **Response 200 (item):**
```json
{
  "id": 1,
  "mailbox_name": "Caixa Jurídica",
  "subject": "...",
  "sender": "remetente@email.com",
  "received_at": "2026-05-19T12:00:00Z",
  "is_dispatched": false,
  "body_text": "...",
  "created_at": "2026-05-19T12:00:01Z"
}
```

---

## Perfis de extração (IA)

### `POST /api/v1/extraction-profiles/`
- **Descrição:** Definição de perfil de extração (prompt e schema Pydantic associado).
- **Auth:** JWT
- **Request:**
```json
{
  "name": "Processos Jurídicos",
  "system_prompt_template": "Extraia dados. Data: {data_atual}",
  "pydantic_schema_name": "ProcessoJuridicoSchema"
}
```
- **Response 201:** campos acima + `id`, `user`

### `PUT / PATCH /api/v1/extraction-profiles/{id}/`
- **Descrição:** Atualização de perfil de extração.
- **Auth:** JWT
- **Request / Response:** mesmos campos

### `GET .../` · `GET .../{id}/` · `DELETE .../{id}/`
- **Descrição:** Listagem, consulta e remoção.

---

## Automações (Workflows)

Rotas equivalentes: `/api/v1/workflows/` e `/api/workflows/automations/`

### `POST /api/workflows/automations/` — Criação
- **Descrição:** Persistência de automação com gatilho e ações. O valor `"Webhook Externo"` em `event_type` gera `webhook_token` (ver seção WEBHOOK).
- **Auth:** JWT
- **Request:**
```json
{
  "name": "WhatsApp boas-vindas",
  "description": "Dispara no webhook",
  "is_active": true,
  "trigger": {
    "connection": 1,
    "event_type": "Webhook Externo",
    "payload_mapping": {}
  },
  "actions": [{
    "action_type": "WHATSAPP_EVOLUTION",
    "payload_template": "{\"number\": \"{{data.phone}}\", \"text\": \"Olá {{data.name}}\"}"
  }]
}
```
- **Response 201:** objeto workflow incluindo `trigger.webhook_token` quando aplicável

### `PUT / PATCH /api/workflows/automations/{id}/`
- **Descrição:** Atualização de automação existente.
- **Auth:** JWT
- **Request / Response:** mesma estrutura do POST

### `GET .../` · `GET .../{id}/` · `DELETE .../{id}/`
- **Descrição:** Listagem, consulta e remoção (`204`).

### `POST /api/workflows/generate/` — Geração por IA (stateless)
- **Descrição:** Geração de rascunho estruturado a partir de prompt; não persiste na base de dados.
- **Auth:** JWT (requer tenant ativo)
- **Rotas equivalentes:** `POST .../automations/generate-from-prompt/` · `POST /api/v1/workflows/generate-from-prompt/`
- **Request:**
```json
{ "prompt": "Webhook com nome e telefone → WhatsApp de boas-vindas" }
```
- **Response 200:**
```json
{
  "workflow_name": "...",
  "workflow_description": "...",
  "trigger": { "event_type": "...", "payload_mapping": {} },
  "actions": [{ "action_type": "WHATSAPP_EVOLUTION", "endpoint_url": null, "payload_template": "..." }]
}
```
- **Erros:** `403` (`no_organization` | `quota_exceeded`) · `422` (`workflow_generation_failed`)

---

## WEBHOOK — Detalhamento

### **`POST /api/workflows/webhooks/catch/{token}/`** `WEBHOOK`
- **Descrição:** Ingestão de payload externo por token UUID; enfileira execução da automação.
- **Auth:** pública · rate limit 60/min
- **Request:**
```json
{ "data": { "phone": "5511999999999", "name": "Maria" } }
```
- **Response 202:**
```json
{ "status": "accepted", "log_id": 42 }
```

### **`POST /api/workflows/webhook/inbound/{connection_id}/`** `WEBHOOK`
- **Descrição:** Recepção de eventos da Evolution API.
- **Auth:** pública
- **Response 202:** `{ "status": "sucesso" }`

### **`POST /api/webhooks/receive/{connection_id}/`** `WEBHOOK`
- **Descrição:** Entrada genérica associada a `AppConnection`.
- **Auth:** pública
- **Response 202:** `{ "status": "success", "message": "Orquestração enfileirada!" }`

### **`POST /api/billing/webhook/`** `WEBHOOK`
- **Descrição:** Notificações de eventos Stripe.
- **Auth:** header `Stripe-Signature`
- **Response:** HTTP `200` ou `400` (sem corpo JSON)

---

## Billing (Stripe)

### `POST /api/billing/checkout/`
- **Descrição:** Criação de sessão de checkout para subscrição de plano.
- **Auth:** JWT
- **Request:**
```json
{ "plan_id": 1 }
```
- **Response 200:**
```json
{ "checkout_url": "https://checkout.stripe.com/..." }
```

---

## Documentação OpenAPI

| Rota | Descrição |
|------|-----------|
| `GET /api/schema/` | Esquema OpenAPI em JSON |
| `GET /api/docs/` | Interface Swagger UI |
| `GET /api/redoc/` | Interface ReDoc |

---

## Observações

- Templates de ação utilizam caminhos diretos do payload recebido (ex.: `{{data.phone}}`); `payload_mapping` ainda não é aplicado em runtime.
- Não existe CRUD REST para `AppConnection`; referência apenas via FK no gatilho.
- CORS em desenvolvimento: origens `localhost:5173` e `127.0.0.1:5173`.
