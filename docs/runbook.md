# 📖 Runbook de Operações

Guia de resposta rápida para incidentes e manutenção.

### 1. Comandos de Emergência
* **Verificar Saúde Total:** `http://localhost:8000/healthz/`
* **Logs em Tempo Real:** Aceder ao Dozzle em `http://localhost:8888`
* **Reiniciar apenas o Worker (Se as tarefas travarem):**
  ```bash
  docker compose restart worker

### 2. Alertas proativos no Sentry (CAD-058)
Configuração feita no painel (Sentry → Alerts → Create Alert → *Issue Alert*):
1. **Environment:** `production` (o back-end envia `environment` via `DJANGO_ENV` e `release` via `APP_VERSION`).
2. **Condição (When):** *A new issue is created* e/ou *The issue changes state from resolved to unresolved*.
3. **Filtro (If):** `event.type equals error` (Exception) e tag `environment equals production`.
4. **Ação (Then):** enviar para Discord/Telegram (via integração/webhook) e/ou e-mail da equipa.
5. Cada evento traz `user.id` e a tag `organization_id` — identifica o escritório afetado.

### 3. Rotação dos logs dos contentores (CAD-058)
`web`, `worker` e `db` usam `json-file` com `max-size: 10m` e `max-file: 5` (~50 MB/contentor, definido em `x-logging` no `docker-compose.yml`). Logs mais antigos que isso deixam de estar disponíveis no Dozzle; para histórico longo use o Sentry/trilha de auditoria.
