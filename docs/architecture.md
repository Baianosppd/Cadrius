# 🏗️ Arquitetura Técnica - Cadrius AI

O Cadrius AI utiliza um padrão de **Event-Driven Architecture (EDA)** simplificado, focado em processamento de linguagem natural.

### 1. Fluxo de Dados (Data Pipeline)
1. **Ingestão:** O `tasks/tasks.py` (via Cron do Django-Q) monitora provedores (IMAP, Webhooks).
2. **Normalização:** Dados brutos são convertidos em objetos `EmailMessage` ou `WebhookEvent`.
3. **Orquestração (Sprint 1):** O app `workflows` identifica qual fluxo deve ser disparado.
4. **Inteligência:** O app `extraction` utiliza LLMs (OpenAI/Claude) para transformar texto não estruturado em JSON estruturado.
5. **Ação:** O app `integrations` dispara a saída para a API de destino (Trello, WhatsApp).



### 2. Stack Tecnológica
* **Engine:** Python 3.11 + Django 5.0 (ASGI)
* **Task Queue:** Django-Q2 com Redis (Broker)
* **Base de Dados:** PostgreSQL 15 (Relacional)
* **Proxy/Gateway:** Traefik v2.10
* **Frontend:** React.js (Comunicação via REST API / JWT)