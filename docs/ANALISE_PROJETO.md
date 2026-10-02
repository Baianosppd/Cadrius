# Análise completa do projeto Cadrius

> Base: leitura integral do **Documento de Especificação de Projeto Integrador (68 p.)** + inspeção de todo o
> código do back-end, Docker, CI/CD e execução real (testes em SQLite e PostgreSQL 16, `check --deploy`, flake8,
> bandit, pip-audit, coverage e telas em Chromium). Data: 02/10/2026.
> Legenda de estado: ✅ confirmado no código · 🟡 parcial · ❌ não existe/não funciona · 🆕 entregue nos CADs 056–071.

## 1. Resumo executivo

| Indicador | Antes (`main`) | Depois (CAD-056…071) |
|---|---|---|
| Testes automatizados | 33 | **150** (SQLite e PostgreSQL), cobertura **82%** (CI exige ≥ 75%) |
| Vulnerabilidades em dependências (`pip-audit`) | não medido (versões soltas; 143 pacotes instalados) | **0** (83 pacotes pinados com hash) |
| Segredos expostos no repositório | senha Gmail no `deploy.yml`, chave Evolution, dumps `.sql.gz` no git | removidos do código (⛔ rotacionar + limpar histórico) |
| Isolamento entre escritórios | só em branch não mesclada | ✅ mesclado + testes de vazamento |
| Trilha de auditoria | inexistente | ✅ imutável, encadeada por hash, trigger no banco |
| LGPD (termos, consentimento, DSR, retenção) | inexistente | ✅ implementado (🟡 textos aguardam revisão jurídica) |
| IA autônoma | sem controle | ✅ política por escritório, humano no circuito, kill switch |
| Telas de monitoramento/conformidade | inexistente | ✅ Centro de Segurança + API |

**Conclusão.** A fundação (Django + DRF + Django-Q + Redis + Postgres + Traefik) é adequada e o fluxo "e-mail →
IA → ação" funciona em teste. O risco maior estava na **distância entre o documento e o código**: vários itens
marcados como *Concluído* no documento não existiam (isolamento de tenant em `main`, auditoria de admin, LGPD,
SSL, e-mail transacional, upload de documentos…). Os CADs 056–071 fecham os riscos de segurança e a maioria das
lacunas de governança; as **pendências funcionais** (seção 5) viram os CADs 072+ em `docs/CADS_BACKLOG.md`.

## 2. Matriz documento × código

### 2.1 Regras de negócio (RNE)

| ID | Documento | Realidade verificada | Estado |
|---|---|---|---|
| RNE-001 Profissional independente de organização | Concluído | `CustomUser` independente + `OrganizationMembership` N:N | ✅ |
| RNE-002 Autenticação híbrida/validação de domínio | Concluído | Adapter SSO **quebrado** (`ImportError` em `billing.models`) — todo login Google/Microsoft falhava | ✅ 🆕 CAD-066 (+ exige e-mail verificado) |
| RNE-003 Isolamento restrito de dados | Concluído | Só em `feature/CAD060-CAD063` (não mesclada); `Workflow.objects.all()` exposto em `main` | ✅ 🆕 CAD-066 |
| RNE-004 Provisionamento por domínio | Em processo | Funcional após a correção do adapter | ✅ 🆕 |
| RNE-005 RBAC | Concluído | Cargo só valia nos convites; `VIEWER` podia escrever | ✅ 🆕 CAD-069 (`OrgRolePermission`) |
| RNE-006 Limites por organização | Em processo | `check_quota_limit` + `check_and_update_quota` (dois mecanismos; status `QUOTA_EXCEEDED` fora de `STATUS_CHOICES`) | 🟡 ver 4.3 |
| RNE-007 Fluxos como máquina de estados | Concluído | Modelo é Workflow/Trigger/Action lineares; **não há** `state_machine`/`WorkflowTemplate`/`WorkflowInstance` | 🟡 divergência de modelo |
| RNE-008 Injeção de contexto dinâmico | Concluído | `render_action_payload` com `{{var}}`; era vulnerável a injeção de JSON | ✅ 🆕 CAD-065 |
| RNE-009 Zero Data Loss | Concluído | Payload é gravado antes de enfileirar (`ExecutionLog`), mas **não há reprocessamento** de logs `PENDING` órfãos se o broker cair | 🟡 CAD-075 |
| RNE-010 Desacoplamento assíncrono | Concluído | Django-Q para IA/envios | ✅ |
| RNE-011 Rastreabilidade de comunicações (registro inalterável) | Concluído | `IntegrationLog` mutável; não havia registro imutável | ✅ 🆕 CAD-067/071 (`message.sent`/`integration.call`) |
| RNE-012 Auditoria privilegiada | Concluído | Inexistente (admin sem rastro) | ✅ 🆕 CAD-067 |
| RNE-013 Propriedade dos dados (30 dias) | Concluído | Inexistente | ✅ 🆕 CAD-068 |
| RNE-014 Deduplicação (1 min) | Concluído | **Inexistente** (e-mail duplicado ignorado só por `message_id`; webhook não deduplica) | ❌ CAD-076 |
| RNE-015 Geração dinâmica de workflows por IA | Em processo | `generate-from-prompt` devolve JSON (não persistia) | ✅ 🆕 CAD-069 (rascunho persistido) |
| RNE-016 Human-in-the-loop | Em processo | Inexistente | ✅ 🆕 CAD-069 |
| RNE-017 Mapeamento inteligente de variáveis | Em processo | `payload_mapping` é gravado e **nunca usado** | ❌ CAD-077 |
| RNE-018 Evolução de templates base | Em processo | Sem biblioteca de templates | ❌ CAD-078 |

### 2.2 Requisitos funcionais (RF) — itens que divergem

| ID | Documento | Realidade | Estado |
|---|---|---|---|
| RF-001 Registro completo (OAB, UF, área) | Concluído | Registro aceita nome/e-mail/CPF/telefone; **OAB/UF/área só no perfil** (e `oab_uf`/`practice_area` não são editáveis) | 🟡 CAD-073 |
| RF-003 SSO Google | Em processo | Quebrado até CAD-066 | 🆕 |
| RF-005 Gestão de organizações (CNPJ, regime…) | Concluído | **Não existe endpoint** de criar/editar organização (só Admin) | ❌ CAD-073 |
| RF-009 Upload de documentos | Concluído | **Não existe** upload (só avatar); sem `DocumentExtraction` | ❌ CAD-074 |
| RF-010 Extração por IA (PDF/imagem) | Em processo | Só texto de e-mail/prompt; sem OCR/PDF | 🟡 CAD-074 |
| RF-012/013 IA gera fluxo + rascunho/aprovação | Em processo | Concluído em CAD-069 | ✅ 🆕 |
| RF-016 Webhooks "validados por assinatura" | Concluído | Token UUID na URL + rate limit; **sem assinatura HMAC** (Evolution inbound sem autenticação) | 🟡 CAD-079 |
| RF-017 Motor de avaliação de gatilhos | Em processo | Gatilho dispara sempre; **não avalia regras/condições** | ❌ CAD-077 |
| RF-018 Data Mapper/limpeza | Concluído | Não implementado | ❌ CAD-077 |
| RF-019 Cofre de credenciais | Concluído | Modelo existe e agora é cifrado, mas **sem API** (CRUD de `AppConnection`) — o front não consegue criar conexões | ❌ CAD-072 |
| RF-020 E-mail transacional | Concluído | `EMAIL_SMTP` levanta `ValueError("não implementado")`; sem backend SMTP | ❌ CAD-080 |
| RF-021 Registro de entrega (SENT/DELIVERED/BOUNCED) | Concluído | Sem `EmailLog`; entrega só como sucesso/falha HTTP | ❌ CAD-080 |
| RF-023 Confirmação de ações | Concluído | Inexistente até CAD-069 | ✅ 🆕 |
| RF-024 Memória contextual (pgvector) | Futuro | Imagem `postgres:15-alpine` **não tem pgvector**; sem RAG | ❌ (futuro) |
| RF-027 Integração com e-mail → dispara fluxo | Concluído | `fetch_emails` grava mensagens, mas **nada despacha** `process_email` (só o script de teste) | ❌ **CAD-075 (crítico)** |
| RF-028 Criar tarefas automáticas | Em processo | `UserTask` existe; **nenhuma ação de workflow cria tarefas** | ❌ CAD-081 |
| RF-029 Registro de execuções | Concluído | `ExecutionLog` ✅ | ✅ |

### 2.3 Requisitos não funcionais (RNF)

| ID | Documento | Realidade | Estado |
|---|---|---|---|
| RNF-004 p95 < 200 ms | Concluído | **Sem medição** (nem teste de carga) | ❌ CAD-082 |
| RNF-008 Proteção em repouso (AES) | Concluído | **Falso** até CAD-065 (`core/utils.py` inexistente, senhas em texto puro) | ✅ 🆕 |
| RNF-009 Audit trail imutável do Admin | Concluído | Inexistente | ✅ 🆕 CAD-067 |
| RNF-010 Conformidade LGPD | Concluído | Inexistente | ✅ 🆕 CAD-068 (🟡 jurídico) |
| RNF-012 Gateway e SSL | Concluído | Traefik só na porta 80, sem TLS | ✅ 🆕 CAD-066 (`docker-compose.prod.yml`; validar em staging) |
| RNF-013 Zero Data Loss | Concluído | idem RNE-009 | 🟡 |
| RNF-014 Flake8 bloqueia merge | Concluído | CI só checava `E9,F63,F7,F82` e o deploy rodava em paralelo ao CI | ✅ 🆕 CAD-066 |
| RNF-015 `makemigrations --check` | Concluído | ✅ (mantido) | ✅ |
| RNF-016 Sentry no front e back | Concluído | Back ✅ (sem `environment`/`release`; PII ligada); **front não verificável** | 🆕 CAD-056 / front |
| RNF-019 Disponibilidade | Não está em produção | Healthchecks, `restart`, backups, rollback automático adicionados | 🆕 |
| RNF-020 Logs de ações do usuário | Concluído | Só `ExecutionLog`/`IntegrationLog` | ✅ 🆕 CAD-067 |

### 2.4 Divergências do texto do documento (corrigir no próximo versionamento)
- **Celery** é citado em 4 lugares; o projeto usa **Django-Q2** (não há Celery).
- **Django Channels, pgvector, Eclipse Mosquitto (MQTT)** constam em "Escolhas Tecnológicas", mas **não existem** no código nem no compose.
- O modelo de dados do documento (`AutomationRule`, `WorkflowTemplate`, `WorkflowInstance`, `DocumentExtraction`, `EmailLog`, `WebhookLog`, `IntegrationConfig`) **não corresponde** ao código (Workflow/Trigger/Action/ExecutionLog/AppConnection/IntegrationLog).
- "Rate limit de 60/min nos webhooks": 60/min aplica-se a `webhook_catch`; o receptor Evolution usa 200/min.
- "Nenhuma chave hardcoded" (§25): havia — ver 3.1.

## 3. Principais pontos falhos (por severidade)

### 3.1 Segurança
| # | Achado | Evidência | Estado |
|---|---|---|---|
| S1 | Senha de app do Gmail em `deploy.yml` | arquivo versionado | ✅ removida · ⛔ **revogar** |
| S2 | Produção assinava JWT com `SECRET_KEY` padrão (deploy gerava `DJANGO_SECRET_KEY`, código lia `SECRET_KEY`) | `settings.py` | ✅ CAD-065 |
| S3 | Evolution API com chave mestra pública + porta 8082 aberta | `docker-compose.yml` | ✅ CAD-065/066 |
| S4 | Sem isolamento entre escritórios em `main` | `Workflow.objects.all()` | ✅ CAD-066 |
| S5 | Dumps `.sql.gz` no git e na imagem Docker | `backups/last/` | ✅ fora do índice/imagem · ⛔ limpar histórico |
| S6 | Credenciais em texto puro | `MailBox.password`, `AppConnection.credentials`, `IntegrationConfig` | ✅ Fernet + migração |
| S7 | CSP inativa (django-csp 4 ignora `CSP_*`) | resposta HTTP sem cabeçalho | ✅ |
| S8 | SSRF em ações de webhook; injeção de JSON em templates | `webhook_executor`, `render_action_payload` | ✅ |
| S9 | **Login em loop infinito se o Redis cair** (`SESSION_ENGINE=cache` + `IGNORE_EXCEPTIONS`) e flush do Redis desloga todos | achado ao testar sessões | ✅ CAD-070 (`cached_db`) |
| S10 | SSO quebrado e sem checar e-mail verificado | `accounts/adapters.py` | ✅ |
| S11 | Escalada de cargo (ADMIN convida OWNER); IDOR em tarefas; VIEWER escreve | serializers/views | ✅ |
| S12 | Stripe: webhook com segredo vazio forjável; checkout sempre 500 | `billing/views.py` | ✅ |
| S13 | Sem MFA; e-mail sem verificação | settings | ❌ CAD-083/084 |
| S14 | `/admin/` público | urls | ❌ CAD-083 |
| S15 | Docker socket montado (mesmo `:ro` é acesso total) no Traefik/Dozzle | compose | 🟡 CAD-085 (socket-proxy) |

### 3.2 Defeitos funcionais encontrados na leitura
1. **SSO quebrado** (`ImportError`) — RF-003. ✅ corrigido.
2. **`/api/workflows/automations/` dava 500** (`ActionSerializer` com campos inexistentes). ✅ corrigido.
3. **`/api/billing/checkout/` sempre 500** (`organizationmembership_set` não existe). ✅ corrigido.
4. **Cadastro sem CPF falhava no 2º usuário** (`''` em campo `unique`). ✅ corrigido.
5. **`test_ai.py` na raiz era executado na descoberta de testes** (chamava OpenAI/Groq/Gemini no CI). ✅ movido para `scripts/`.
6. **`process_email` nunca é agendado** → RF-027 incompleto. ❌ CAD-075.
7. **`integrations/telegram.py`** usa `mailbox.integration_config` (não existe) → código morto/quebrado. ❌ CAD-086.
8. **Duplicidade**: `tasks` app contém `IntegrationConfig`/`IntegrationLog` legados; `billing/middleware.py` (`MultiTenantMiddleware`) não usado; app `webhooks` (`<uuid:connection_id>`) inalcançável porque `AppConnection.id` é inteiro. ❌ CAD-086.
9. Cota de IA: `check_quota_limit` (decorator) + `check_and_update_quota` (worker) e status `QUOTA_EXCEEDED` fora de `STATUS_CHOICES`. ❌ CAD-087.
10. `requirements.txt` em UTF-16, sem versões, com pandas/scikit-learn/matplotlib/etc. sem uso. ✅ CAD-066.

## 4. Análise de arquitetura

### 4.1 O que está bom
- Apps por domínio, API versionada, Django-Q desacoplando IA/envios, Traefik + redes Docker segregadas.
- Modelo multi-tenant coerente (Organization ↔ Membership ↔ User) e Pydantic validando a saída da IA.

### 4.2 Ajustes feitos nesta rodada
```
Cliente (React) ──HTTPS──▶ Traefik (TLS, HSTS) ──▶ web (Django/DRF, uvicorn)
                                                   ├─ AuditContextMiddleware (request_id, IP, ator)
                                                   ├─ TenantMiddleware + SentryJWTAuthentication (tenant, 428 sem aceite)
                                                   ├─ apps: accounts, billing, emails, workflows, integrations, extraction, tasks
                                                   └─ apps de governança: audit · privacy · aigov · compliance
                         worker (Django-Q) ◀── Redis (senha, AOF) ──▶ web
                         Postgres (trigger de imutabilidade na trilha) · Evolution API (schema próprio) · Dozzle (BasicAuth)
```
- **Governança como camada transversal**: `audit` (quem/o quê/quando, imutável), `privacy` (consentimento/DSR/retenção),
  `aigov` (política/guarda de IA), `compliance` (controles ISO/LGPD calculados do ambiente real).
- **IA sob guarda**: `run_guarded` envolve toda chamada (política → execução → registro sem conteúdo).
- **Compose em 3 arquivos**: base segura, `override` de desenvolvimento (carregado automaticamente) e `prod` (TLS).

### 4.3 Dívida técnica remanescente
Ver itens 6–9 de 3.2 e CAD-086/087. Também: `ExecutionLog.trigger_payload` guarda o payload bruto (necessário para
reprocessar) — mitigado por retenção de 90 dias; ideal é criptografá-lo (CAD-088).

## 5. Pendências funcionais (back-end) — viram CADs
RF-027 despacho de e-mails (**crítico**), RF-019 API de conexões, RF-005/001 organização e cadastro completo,
RF-009/010 upload e extração de documentos, RF-017/018 avaliação de gatilhos e mapeamento, RF-020/021 e-mail transacional,
RNE-014 deduplicação, RNE-009 reprocessamento, RF-028 tarefas automáticas, assinatura HMAC de webhooks,
RNF-004 medição de desempenho. Detalhes e critérios de aceite em `docs/CADS_BACKLOG.md`.

## 6. Análise DevSecOps

### 6.1 Cadeia de suprimentos
| Item | Antes | Depois |
|---|---|---|
| Dependências | 84 linhas sem versão (UTF-16), libs pesadas sem uso | `requirements.in` (26 diretas) → `requirements.txt` com hashes (`--require-hashes`) |
| CVEs | não verificado | `pip-audit` bloqueante no CI + Dependabot semanal → **0 vulnerabilidades** hoje |
| Imagem | root, gcc, `COPY .` incluía backups/.git | sem root, sem compilador, `.dockerignore` endurecido, Trivy no CI |
| Segredos no código | sim | gitleaks no CI (não bloqueante até sanear o histórico) |

### 6.2 Pipeline (CI/CD)
- `ci.yml` reutilizável: flake8 (pyflakes), bandit, pip-audit, gitleaks, testes em **Postgres + Redis** com cobertura ≥ 75%,
  `check --deploy`, `makemigrations --check`, validação do compose (dev e prod), build, imagem sem root, Trivy.
- `deploy.yml` só roda **depois** do CI; valida secrets; gera `.env` com `umask 077`; `docker compose -f … -f prod`;
  *smoke test* em `/readyz/` e **rollback automático**; cópia dos dumps antigos antes do `git reset`.

### 6.3 Contêineres e rede
- Base segura (`no-new-privileges`, `cap_drop: ALL` em web/worker, limites de CPU/memória, healthchecks, logs com rotação).
- Somente Traefik publica portas (80/443). Painel do Traefik, 8000, Evolution e ngrok só em `127.0.0.1` (dev).
- Redis com senha + AOF; Postgres sem senha padrão em produção; Evolution em **schema próprio** (antes dividia `public` com o Django).
- TLS Let's Encrypt, redirecionamento 80→443, HSTS (`docker-compose.prod.yml`). ⚠️ **Não foi possível subir o Docker neste ambiente**
  (sem daemon): o compose foi validado com `docker compose config`, mas o primeiro deploy deve passar por *staging*.

### 6.4 Observabilidade e resposta
- Logs estruturados (`chave=valor`, `execution_log_id`, `request_id`) → Dozzle (BasicAuth); Sentry sem PII, com `environment`/`release` e tags de usuário/escritório.
- `/healthz` (sem vazar erros) e `/readyz` (banco + cache). Alertas de anomalia + e-mail (`SECURITY_ALERT_EMAILS`).
- Backup diário do compose + `backup_to_supabase` **cifrado** + `decrypt_backup` (restauro testável).

### 6.5 Riscos residuais (DevSecOps)
1. Histórico do git ainda contém a senha do Gmail e os dumps → rotacionar e `git filter-repo` (⛔ manual).
2. Docker socket montado em Traefik/Dozzle → `docker-socket-proxy` (CAD-085).
3. Sem WAF/limite por IP no Traefik; `/admin/` público e sem MFA (CAD-083).
4. Sem monitoramento de disponibilidade externo (Sentry Uptime/UptimeRobot) e sem testes de restauração periódicos (CAD-089).
5. Banco/Redis sem alta disponibilidade (ISO 27001 A.8.14).

## 7. Qualidade de testes
- 150 testes: segurança (SSRF, injeção, criptografia, headers, RBAC, IDOR), trilha (cadeia, trigger no Postgres, anomalias),
  LGPD (aceite, DSR, retenção, offboarding), IA (guarda, rascunhos, revisão), conformidade (catálogo, telas, API).
- Cobertura 82%. Pontos fracos: `tasks/tasks.py` (30% — IMAP/IA), `integrations/evolution.py`, `workflows/webhooks.py`, `billing/views.py`.
- Não existem: testes de carga (RNF-004), E2E com o front, testes de restauração de backup.
