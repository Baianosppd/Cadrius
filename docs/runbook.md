# 📖 Runbook de Operações

Guia de resposta rápida para incidentes e manutenção.

### 1. Comandos de Emergência
* **Verificar Saúde Total:** `http://localhost:8000/healthz/`
* **Logs em Tempo Real:** Aceder ao Dozzle em `http://$DOZZLE_HOST` (via Traefik, com BasicAuth; sem porta publicada)
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


### 4. Centro de Segurança (rotina diária)
Acesse `/security-center/` (login pelo Admin, usuário *staff*). Checklist diário (5 min):
1. **Visão geral** — cadeia de auditoria *Íntegra*? alertas críticos/altos abertos? IA ligada?
2. **Alertas** — triar (Em análise / Resolvido / Falso positivo). SLA: crítico/alto em 24 h.
3. **Privacidade** — pedidos de titulares perto do vencimento (15 dias).
4. **Governança de IA** — fila de confirmação humana e rascunhos pendentes.
Semanal: exportar a matriz ISO/LGPD (CSV) e revisar controles "Não implementado". Mensal: `python manage.py snapshot_compliance` (já agendado) e revisar tendência.

### 5. Resposta a incidente de segurança (LGPD art. 48 · ISO 27001 A.5.24–A.5.28)
| Etapa | Ação | Prazo |
|---|---|---|
| 1. Detectar/triar | Alerta no Centro de Segurança, Sentry ou relato; abrir registro (quem, quando, o quê) | imediato |
| 2. Conter | **Kill switch de IA** (se envolver IA), revogar tokens (`/api/v1/auth/logout/`, `TokenBlacklist`), desativar usuário/organização, rotacionar chaves expostas | < 1 h |
| 3. Preservar evidência | Exportar eventos por `request_id` (CSV) e logs do Dozzle; `verify_audit_chain`; não apagar nada | < 4 h |
| 4. Avaliar | Dados afetados (categorias do RoPA), titulares, risco ou dano relevante? | < 24 h |
| 5. Comunicar | Havendo risco/dano relevante: **ANPD e titulares em prazo razoável (referência: 3 dias úteis)**; avisar controladores (escritórios) | ≤ 3 dias úteis |
| 6. Erradicar/recuperar | Corrigir causa raiz, restaurar (ver abaixo), reforçar controles | — |
| 7. Aprender | Post-mortem sem culpa, atualizar regras de anomalia/RoPA/RIPD | ≤ 10 dias |

### 6. Rotação de segredos
- **Chave de criptografia (`ENCRYPTION_KEY`)**: definir `ENCRYPTION_KEY="nova,antiga"` → o sistema decifra com ambas e cifra com a primeira;
  rodar `python manage.py shell -c "from emails.models import MailBox; [m.save() for m in MailBox.objects.all()]"` (idem `AppConnection`/`IntegrationConfig`) e então remover a antiga.
- **`DJANGO_SECRET_KEY`**: invalida sessões/JWT (todos precisam logar de novo). **Postgres/Redis/Evolution**: alterar no `.env` + `ALTER USER` (Postgres) e redeploy.
- **Senha de app do Gmail (IMAP)**: revogar no Google e criar novo secret `PROD_IMAP_PASSWORD`.

### 7. Backup e restauração
1. Backup: `docker compose exec web python manage.py backup_to_supabase` (cifrado; agendável via `setup_security_schedules`).
2. Restaurar: baixar o `.enc` do bucket → `python manage.py decrypt_backup arquivo.dump.enc arquivo.dump` → `pg_restore -d cadrius arquivo.dump`.
3. **Testar a restauração em staging a cada trimestre** (evidência para ISO 27001 A.8.13).
