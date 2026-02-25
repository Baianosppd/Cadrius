# architecture.md: Arquitetura Base do Sistema de Automação com IA

## Visão Geral

O sistema é uma arquitetura de microsserviços monólito (um único repositório Django) focado no processamento assíncrono de eventos (e-mails). O backend em Django/DRF serve tanto a API para o frontend quanto hospeda o motor de processamento assíncrono (Workers).

## Componentes Chave

| Componente | Proprietário | Tecnologia/App | Responsabilidade |
| :--- | :--- | :--- | :--- |
| **API/Backend Core** | Jullio | Django/DRF (`core`, `emails`) | Gerenciamento de usuários, CRUD de `MailBox` e `EmailMessage`, Autenticação (JWT), Saúde (`/healthz`). |
| **Banco de Dados** | Jullio | SQLite (Local), PostgreSQL (Prod) | Persistência de dados: emails, regras de processo, logs de integração. |
| **Broker/Workers** | Thales | **Django-Q** (usando ORM) | Gerenciamento e execução de tarefas assíncronas (fetch, processamento, notificação). |
| **Módulo de Extração (IA)** | Juliano | Python/OpenAI (`extraction`) | Chamada ao ChatGPT, Prompting, e Validação do JSON extraído (Pydantic). |
| **Módulo de Integração** | Thales | Python/Requests (`integrations`) | Adaptadores de serviços externos (Trello, Telegram). |

## Fluxo de Dados (Pipeline Assíncrono)

O coração do sistema é o pipeline assíncrono gerenciado pelo **Django-Q**.

1.  **Gatilho (Beat):** O *scheduler* do Django-Q (Beat) executa periodicamente a tarefa **`tasks.fetch_emails`**.
2.  **Captura (Thales):** O *worker* `fetch_emails` se conecta à `MailBox` (lida do DB de Jullio via IMAP), baixa emails novos, e os salva como **`EmailMessage`** com `status='PENDING'`.
3.  **Enfileiramento (Thales):** Após salvar, o *worker* enfileira uma nova tarefa para cada email: **`tasks.process_email(email_id)`**.
4.  **Extração (Juliano):** O *worker* `process_email` chama o módulo **`ai_wrapper.extract_fields_from_text`** de Juliano. O *output* (JSON validado) é persistido no campo `extracted_data` do `EmailMessage`.
5.  **Integração (Thales):** Se a extração for bem-sucedida, o *worker* chama:
    * `integrations.create_trello_card(extracted_data)`
    * `integrations.notify_telegram(log_message)`
6.  **Finalização:** O *status* do `EmailMessage` é atualizado para `'INTEGRATED'` ou `'FAILED'`, e o **`IntegrationLog`** é salvo.
7.  **API (Jullio):** O frontend (ou administradores) podem consultar o `EmailMessage` (incluindo `extracted_data` e *status*) via API DRF de Jullio.

## Decisões de Desenvolvimento Local

* **DB:** Uso de **SQLite** para agilizar o setup.
* **Assíncrono:** Uso de **Django-Q** com backend ORM para evitar dependências externas (Redis/RabbitMQ) no ambiente local.
* **Mocks:** Juliano e Thales usarão **mocks** em seus testes unitários para evitar o consumo de API Key e tempo de resposta em testes de CI.