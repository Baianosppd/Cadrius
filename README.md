# ⚖️ Cadrius AI - Hiperautomação Jurídica

O **Cadrius AI** é uma plataforma SaaS de orquestração de fluxos de trabalho projetada para o setor jurídico. O sistema captura eventos (E-mails, Webhooks), processa dados via IA (LLMs) e executa ações automáticas em ferramentas externas (Trello, WhatsApp, Astrea).

---

## 🚀 Arquitetura do Sistema

A aplicação utiliza uma arquitetura de micro-serviços orquestrada via **Docker**, garantindo isolamento e escalabilidade.



* **Traefik:** Proxy reverso e roteamento de entrada (Porta 80).
* **Django (Uvicorn/ASGI):** API Core e motor de regras.
* **PostgreSQL:** Banco de dados relacional (Isolado em rede interna).
* **Redis:** Broker para mensagens e cache.
* **Django-Q (Worker):** Processamento assíncrono de tarefas pesadas.
* **Dozzle:** Monitoramento de logs em tempo real.

---

## 🛠️ Configuração de Desenvolvimento

### Pré-requisitos
* Docker & Docker Compose
* Git

### Passo a Passo
1.  **Clone o repositório:**
    ```bash
    git clone [https://github.com/julliodutra/cadrius.git](https://github.com/julliodutra/cadrius.git)
    cd cadrius
    ```

2.  **Configure as variáveis de ambiente:**
    Crie um arquivo `.env` na raiz seguindo o modelo (solicite a `ENCRYPTION_KEY` ao DevSecOps):
    ```env
    DEBUG=True
    SECRET_KEY=sua_chave_secreta
    ENCRYPTION_KEY=sua_chave_fernet_gerada
    DATABASE_URL=postgres://postgres:postgres@db:5432/cadrius
    REDIS_URL=redis://redis:6379/0
    ```

3.  **Suba os containers:**
    ```bash
    docker compose up --build -d
    ```

4.  **Acesse a aplicação:**
    * **API/Admin:** `http://localhost:8000/admin/`
    * **Swagger (Docs):** `http://localhost:8000/swagger/`
    * **Logs (Dozzle):** `http://localhost:8888`

---

## 🧑‍💻 Equipe
* **Jullio Cesar:** DevSecOps & Infra
* **Thales:** Back-end Engineer
* **Allan:** Product Design (UX/UI)
* **Ryan:** Front-end Engineer