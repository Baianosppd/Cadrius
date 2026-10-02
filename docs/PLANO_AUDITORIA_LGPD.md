# Plano: Trilha de Auditoria + Termos de Ciência (LGPD / ISO 27001 / ISO 27701)

> Status: **PLANEJAMENTO** — nada deste documento foi implementado ainda.
> Base: leitura do código em `main` (Django 5 + DRF/JWT + allauth + django-axes + Django-Q2 + Redis + Postgres + Sentry).

---

## 0. Resumo executivo

O Cadrius processa dados de **terceiros que nem sabem que o sistema existe** (e-mails de clientes de escritórios de advocacia, números de WhatsApp, payloads de webhook, dados processuais) e envia parte deles a **LLMs externos** (OpenAI/Gemini/Groq). Isso nos torna **operador** (LGPD art. 5º, VII) dos escritórios (controladores) e **controlador** dos dados dos próprios usuários/advogados. A trilha de auditoria precisa responder, para qualquer incidente ou pedido de titular: **quem, o quê, quando, de onde, sobre qual dado, com qual base legal e com qual resultado**.

Hoje o sistema tem apenas: log de tentativas de login (`django-axes`), `ExecutionLog`/`IntegrationLog` (operacionais, **mutáveis** e com PII em claro), Sentry (disponibilidade/erros) e logs de container (Dozzle). **Não existe trilha de auditoria, consentimento, registro de tratamento, retenção nem canal do titular.**

### Achados do código que mudam a prioridade (corrigir ANTES/junto da auditoria)

| # | Achado | Local | Risco |
|---|--------|-------|-------|
| F1 | **Backups `.sql.gz` com dados reais versionados no git** (8 arquivos) | `backups/last/` (tracked) | 🔴 Vazamento de PII em histórico git; incidente notificável (art. 48) |
| F2 | Sentry com `send_default_pii=True` e `traces_sample_rate=1.0` | `cadrius/settings.py:33-38` | 🔴 Envia IP/e-mail/cookies/headers a terceiro (transferência internacional, art. 33) sem base/transparência |
| F3 | Docs dizem que credenciais são criptografadas (`core/utils.py`, Fernet) — **o arquivo não existe**; `MailBox.password` e `AppConnection.credentials` estão em texto puro | `docs/SECURITY.md`, `emails/models.py:19`, `integrations/models.py:30` | 🔴 Controle declarado ≠ controle real (pior em auditoria ISO) |
| F4 | `ExecutionLog.trigger_payload/final_result`, `IntegrationLog.request_data/response_body`, `EmailMessage.body_text` guardam PII sem retenção, sem mascaramento, sem expurgo | `workflows/models.py`, `integrations/models.py`, `emails/models.py` | 🟠 Minimização/necessidade (art. 6º III), eliminação (art. 16) |
| F5 | JWT sem blacklist: `BLACKLIST_AFTER_ROTATION=True` mas `token_blacklist` não está em `INSTALLED_APPS`; logout não revoga | `settings.py:210` | 🟠 Não há como encerrar sessão comprometida |
| F6 | Cadastro sem consentimento/aceite de termos; `ACCOUNT_EMAIL_VERIFICATION='none'` | `accounts/serializers.py`, `settings.py:162` | 🟠 Sem prova de ciência/base legal |
| F7 | Sem `LOGGING` configurado (só `logging.getLogger` solto, sem formato/estrutura/redação) | `settings.py` | 🟠 Logs não correlacionáveis nem sanitizados |
| F8 | `TenantMiddleware` pega o **primeiro** membership ativo; `MailBox`/`ExtractionProfile`/`AppConnection`/`EmailMessage` são ligados a `user`, não a `Organization` | `cadrius/middleware.py`, models | 🟠 Auditoria por escritório fica ambígua; risco de acesso cruzado |
| F9 | Admin do Django é "visão global" sem registro de quem consultou o quê | `middleware.py:13` | 🟠 Acesso privilegiado não auditado (ISO A.8.2/A.8.15) |
| F10 | Segredos com default inseguro (`SECRET_KEY`, `EVOLUTION_API_GLOBAL_KEY`), `ALLOWED_HOSTS` com túnel ngrok fixo | `settings.py:41,45,141` | 🟡 Higiene (ISO A.8.9) |

---

## 1. Escopo e mapeamento normativo

| Requisito | Norma | O que entregamos |
|-----------|-------|------------------|
| Registro das operações de tratamento | LGPD art. 37 | ROPA (`docs/compliance/ROPA.md`) + eventos `data.*` na trilha |
| Base legal / consentimento comprovável | LGPD arts. 7º, 8º | Modelo `ConsentRecord` versionado, imutável |
| Transparência e finalidade | LGPD arts. 6º I/VI, 9º | Termo de Ciência + Política de Privacidade + lista de suboperadores |
| Direitos do titular | LGPD art. 18 | Endpoints/fluxo DSR (acesso, correção, eliminação, portabilidade, revogação) |
| Segurança e prevenção | LGPD arts. 46-49 | Detecção de anomalia, runbook de incidente, prazo de comunicação à ANPD |
| Eliminação/retenção | LGPD art. 15-16 | Política de retenção + job de expurgo auditado |
| Transferência internacional | LGPD art. 33 | Inventário de suboperadores (OpenAI, Google, Groq, Sentry, Stripe, Supabase) + cláusulas |
| A.5.15/A.8.2/A.8.3 Controle de acesso | ISO 27001:2022 | RBAC auditado, revisão periódica de acessos |
| **A.8.15 Registro (logging)** | ISO 27001:2022 | Trilha central, imutável, sincronizada em relógio |
| **A.8.16 Monitoramento** | ISO 27001:2022 | Regras de anomalia + alertas |
| A.8.17 Sincronização de relógio | ISO 27001:2022 | UTC em todos os eventos, NTP no host |
| A.5.24-A.5.28 Gestão de incidentes | ISO 27001:2022 | Runbook + evidência vinda da trilha |
| A.8.10 Exclusão de informação | ISO 27001:2022 | Expurgo/retenção |
| A.8.24 Criptografia | ISO 27001:2022 | Criptografia de segredos e PII sensível |
| A.8.13 Backup | ISO 27001:2022 | Backup criptografado, fora do git |
| 27701 (PIMS) 7.2.x / 8.x | ISO 27701 | Consentimento, ROPA, atendimento ao titular, operador |

> ⚠️ Conformidade é **processo + evidência**, não só código. Itens organizacionais (DPO/encarregado, RIPD, contratos de operador, política assinada) estão na Fase 6 e **dependem de você/jurídico**.

---

## 2. Arquitetura da trilha de auditoria

### 2.1 Princípios
1. **Append-only**: ninguém (nem superadmin) edita/apaga evento; correção = novo evento.
2. **Quem/o quê/quando/onde/resultado** em todo evento; UTC.
3. **Nunca registrar valor de PII/segredo** — registrar *referência* (id, campos alterados, hash), não conteúdo.
4. **Fora do caminho crítico**: gravação assíncrona (Django-Q) com fallback síncrono para eventos de segurança; falha de auditoria nunca derruba a request, mas gera alerta.
5. **Separada dos logs operacionais**: `AuditEvent` ≠ `ExecutionLog` ≠ log de aplicação.
6. **Cada escritório enxerga só a sua trilha**; só o time de segurança vê a global (e esse acesso também é auditado).

### 2.2 Novo app `audit`

```
audit/
  models.py        # AuditEvent, ConsentRecord(*), DataSubjectRequest(*), AnomalyAlert
  service.py       # audit.log(event, actor, target, outcome, **meta)  ← API única
  middleware.py    # AuditContextMiddleware: request_id, ip, ua, actor, tenant (contextvars)
  signals.py       # login/logout/falha (django + axes + allauth), mudança de permissão
  mixins.py        # AuditedModelViewSet / @audited para views DRF
  redaction.py     # mascaramento (CPF, e-mail, telefone, tokens, body)
  detectors.py     # regras de anomalia (Fase 4)
  retention.py     # expurgo/anonimização
  admin.py         # somente leitura, sem add/change/delete
  api.py           # GET /api/v1/audit/events/ (escopo por org, filtros, export CSV)
```
(*) `ConsentRecord`/`DataSubjectRequest` podem ficar em app `privacy` para separar responsabilidades; decisão na Fase 3.

### 2.3 Modelo `AuditEvent` (campos)

| Campo | Observação |
|-------|-----------|
| `id` (UUID), `occurred_at` (UTC, index) | |
| `request_id` | correlaciona com Sentry (`sentry_sdk.set_tag`) e logs de app |
| `actor_type` (`user`/`system`/`webhook`/`admin`/`anonymous`), `actor_id`, `actor_label` | label = e-mail **mascarado** |
| `organization_id` | tenant (index) — resolvido de forma explícita, não "primeiro membership" |
| `action` | catálogo fechado `categoria.verbo` (ver 2.4) |
| `target_type`, `target_id` | ex.: `Workflow`/`uuid` |
| `outcome` (`success`/`denied`/`error`), `reason` | |
| `ip`, `user_agent_hash`, `geo_country` | IP truncado após N dias (retenção) |
| `auth_method` (`jwt`/`session`/`sso-google`/`apikey`/`webhook-token`) | |
| `changes` (JSON) | só **nomes de campos** + before/after para campos não sensíveis; sensíveis = `"<redacted>"` |
| `data_categories` (array) | `identificacao`, `contato`, `processual`, `credencial`… (liga à ROPA) |
| `legal_basis` | `contrato`/`consentimento`/`legitimo_interesse`/`obrigacao_legal`… |
| `prev_hash`, `hash` | **cadeia de hash** (cada evento inclui hash do anterior) → evidência de adulteração |

Controles de integridade:
- Tabela com `REVOKE UPDATE, DELETE` para o role da aplicação (role de escrita só `INSERT`), via migration `RunSQL`; trigger `BEFORE UPDATE/DELETE → RAISE EXCEPTION` como segunda barreira.
- Job diário que **ancora** o hash do dia (arquivo em storage WORM/Supabase com versionamento) e verifica a cadeia; divergência → alerta crítico.
- Particionamento mensal (Postgres) → expurgo por partição e consultas rápidas.
- **Cópia fora do banco** (shipping para storage/SIEM) para que comprometer o app não permita reescrever a história.

### 2.4 Catálogo de eventos (v1)

**Autenticação & sessão** — `auth.login.success|failure|locked`, `auth.logout`, `auth.token.refresh`, `auth.token.revoked`, `auth.password.change|reset`, `auth.sso.login|link`, `auth.mfa.*` (Fase 5)
**Conta & acesso** — `user.created|updated|deactivated`, `member.invited|role_changed|removed`, `org.updated|plan_changed`, `admin.login`, `admin.view|change` (django admin)
**Dados pessoais (leitura sensível)** — `data.read` (detalhe de e-mail/log de execução/payload), `data.export`, `data.bulk_read` (listagens > N itens), `data.download`
**Dados (escrita)** — `connection.created|updated|credential_rotated|deleted`, `mailbox.*`, `workflow.created|updated|activated|deleted`, `extraction_profile.*`
**Processamento por terceiros** — `ai.request` (provedor, modelo, **categorias** de dados, nº de tokens, **sem conteúdo**), `integration.call` (destino, status), `message.sent` (canal, destinatário **hash**)
**Privacidade** — `consent.granted|revoked|reprompted`, `dsr.opened|fulfilled|rejected`, `retention.purged`, `anonymization.run`
**Segurança** — `anomaly.detected`, `ratelimit.hit`, `permission.denied`, `webhook.invalid_token`, `audit.chain_broken`, `audit.export`, `audit.viewed`

### 2.5 Pontos de captura no código atual

| Origem | Como |
|--------|------|
| Login JWT (`CustomTokenObtainPairView`) | sobrescrever `post` + sinais do axes (`user_locked_out`) e `user_logged_in/out/login_failed` |
| allauth SSO (`B2BSocialAccountAdapter`) | `pre_social_login`/`save_user` → `auth.sso.*`; **auditar o ramo `is_active=False`** (hoje só `logger.warning`) |
| Views DRF (`ModelViewSet`s) | `AuditedMixin` em `perform_create/update/destroy` + `retrieve` para recursos sensíveis |
| Admin Django | `ModelAdmin` base (`AuditedAdmin`) sobrescrevendo `log_*`/`has_view_permission`, ou usar `LogEntry` + `change_view` hook |
| Webhooks (`workflows/webhooks.py`, `webhooks/views.py`) | evento por chamada: token válido/inválido, origem, payload **size + hash** |
| Pipeline IA (`extraction/ai_wrapper.py`) | `ai.request` antes da chamada: provedor, modelo, categorias, tamanho — alimenta o inventário de suboperadores |
| Django-Q tasks | herdar `request_id`/`actor` no payload da task (contextvars → kwargs) |
| `TeamMemberListCreateView` / `permission_groups` | `member.*` com role antigo → novo |
| Mudança em modelos fora de views (shell, tasks, migrações de dados) | sinais `post_save/post_delete` em lista allow-list de modelos (rede de segurança) |

### 2.6 Estratégia de logs de aplicação (complementar, não substitui a trilha)
- `LOGGING` em JSON (`python-json-logger`/`structlog`) com `request_id`, `org_id`, `user_id` (id, **nunca e-mail**).
- Filtro de **redação** global (CPF, e-mail, telefone, JWT, `Authorization`, senhas, `body_text`) — vale para logger e para Sentry (`before_send`).
- Níveis: `AUDIT` (custom) → arquivo/stdout dedicado + banco; `INFO/WARN/ERROR` → stdout (Dozzle) → Loki/ELK (Fase 4).
- Remover `logger.info` com e-mail do usuário (ex.: `accounts/adapters.py`) → usar `user_id`.
- Sentry: `send_default_pii=False`, `traces_sample_rate` ~0.1, `before_send` com scrubber, `set_user({"id": ...})` apenas, região de dados da UE/BR se disponível. Documentar Sentry como suboperador.

---

## 3. Detecção de atividade anômala (inclusive de usuário autenticado)

> Pedido central: **usuário legítimo agindo fora do padrão** (conta comprometida, insider, exfiltração).

### 3.1 Baseline por usuário/organização
Tabela `UserActivityBaseline` (recalculada diariamente por job): horários habituais, países/ASNs/IPs, volume médio diário de `data.read`/`data.export`, dispositivos (hash de UA), recursos normalmente acessados.

### 3.2 Regras (v1 — determinísticas, explicáveis, baratas)

| ID | Regra | Severidade | Ação |
|----|-------|-----------|------|
| A1 | Login de **novo país/ASN** ou *impossible travel* (> ~800 km/h entre eventos) | Alta | alerta + exigir reautenticação/MFA |
| A2 | Atividade fora da janela habitual (ex.: 02h–05h, baseline) | Média | alerta ao usuário (e-mail) |
| A3 | **Pico de leitura**: `data.read` > média + 3σ (ou > N em 10 min) | Alta | alerta + throttling |
| A4 | **Export/download em massa** ou 1º export da conta | Alta | exigir confirmação, alerta ao OWNER |
| A5 | Enumeração: sequência de IDs/404/403 em recursos de outro tenant | Crítica | bloqueio temporário + alerta segurança |
| A6 | Múltiplas falhas de login → sucesso (padrão *credential stuffing*) | Alta | alerta, forçar reset |
| A7 | Mudança de privilégio (`member.role_changed` p/ ADMIN/OWNER) fora de horário, ou por conta nova | Alta | alerta OWNER |
| A8 | Credencial de integração criada/rotacionada + imediato disparo de workflow para destino novo | Alta | alerta |
| A9 | Webhook com token inválido repetido / origem nova | Média | rate limit + alerta |
| A10 | Mesmo usuário em ≥ 3 IPs/dispositivos simultâneos | Média | alerta |
| A11 | Acesso de **admin Django** a dados de cliente | Alta | alerta + justificativa obrigatória (campo "motivo") |
| A12 | `ai.request` com volume/categorias fora do normal (ex.: documento processual enviado a provedor não aprovado) | Alta | bloquear provedor não allow-listed |

Implementação: `detectors.py` roda (a) **em linha** só para regras baratas (A5, A6, A9 via Redis counters, que já temos) e (b) **em lote** (Django-Q a cada 5 min) para o resto. Gera `AnomalyAlert` (+ `AuditEvent anomaly.detected`) → notificação por e-mail/Telegram/Sentry (já há integração Telegram) → fila de triagem no admin de segurança com SLA.

### 3.3 Fase posterior (v2)
Scoring de risco por sessão, *step-up auth* dinâmico, e eventualmente modelo estatístico (isolation forest) — **só depois** de 60–90 dias de dados e de medir falsos positivos das regras determinísticas.

### 3.4 Visibilidade para o cliente
Tela "Atividade da conta" (usuário vê seus logins/dispositivos e pode **encerrar sessões**) e "Auditoria do escritório" (OWNER/ADMIN vê trilha da própria organização, exporta CSV). Reaproveita/estende `ActivitiesView`.

---

## 4. Termos de Ciência e Consentimento (dados utilizados)

### 4.1 Documentos (conteúdo jurídico — **revisar com advogado/DPO**)
| Documento | Conteúdo mínimo |
|-----------|-----------------|
| **Termos de Uso** | escopo do serviço, papéis (Cadrius=operador, escritório=controlador), responsabilidades |
| **Política de Privacidade** | dados coletados por categoria, finalidade, base legal, retenção, direitos, contato do encarregado |
| **Termo de Ciência de Tratamento de Dados** | lista objetiva de **quais dados** o sistema usa: cadastro (nome, e-mail, CPF, OAB, telefone), conteúdo de e-mails lidos via IMAP, mensagens WhatsApp (Evolution), payloads de webhook, dados extraídos por IA, logs de acesso/IP; **para quê**; **com quem compartilha** |
| **Aviso sobre IA** | trechos de conteúdo são enviados a OpenAI/Google/Groq para extração; sem decisão automatizada exclusiva (art. 20); opção de provedor por perfil |
| **Cláusula de responsabilidade do controlador** | o escritório declara ter base legal para colocar dados de seus clientes no Cadrius (esse é o ponto jurídico mais crítico: o consentimento do usuário **não** cobre os terceiros dentro dos e-mails) |
| **Lista de suboperadores** (página pública versionada) | OpenAI, Google (Gemini/OAuth/Sheets), Groq, Microsoft (SSO), Stripe, Supabase (backup), Sentry, Meta/Evolution (WhatsApp), Trello/ClickUp/Astrea — país, finalidade, categorias |

### 4.2 Modelo de dados

```text
LegalDocument      (slug, kind[terms|privacy|ciencia|ai_notice|dpa], version, content_md,
                    content_sha256, published_at, requires_reconsent, locale)   ← imutável após publicar
ConsentRecord      (id, user, organization?, document FK(version), purpose, legal_basis,
                    granted_at, revoked_at?, ip, user_agent_hash, method[checkbox|click|api],
                    evidence_sha256)                                             ← append-only; revogar = novo registro
SubprocessorEntry  (name, country, purpose, data_categories, dpa_url, active)
```
- **Granularidade** (art. 8º §4º): consentimentos separados e opcionais para o que não é essencial (ex.: analytics, e-mail de produto); termos/ciência de tratamento necessário **não** são "consentimento" mas **ciência registrada** — modelar `legal_basis` corretamente (contrato/legítimo interesse) para não usar consentimento onde não cabe.
- `evidence_sha256` = hash do texto exato exibido → prova de **qual versão** foi aceita.

### 4.3 Fluxos
1. **Cadastro** (`UserRegistrationSerializer`): campos obrigatórios `accepted_terms_version`, `accepted_ciencia_version` (+ opcionais por finalidade). Rejeitar sem aceite → 400. Grava `ConsentRecord` + `AuditEvent consent.granted`.
2. **SSO/allauth**: primeiro login via Google/Microsoft cai em tela de aceite antes de ativar (hoje o usuário entra sem nenhum aceite).
3. **Reaceite**: ao publicar versão com `requires_reconsent`, middleware/DRF permission devolve `428 Precondition Required` + `{"pending_documents":[...]}` até aceitar (frontend mostra modal).
4. **Escritório (OWNER)**: aceite adicional do **DPA/cláusula de controlador** ao criar/ativar a `Organization` e ao conectar uma nova fonte (MailBox/WhatsApp) — "declaro ter base legal para tratar os dados de terceiros que passarão por esta conexão".
5. **Revogação/gestão**: tela "Privacidade" lista aceites e permite revogar os opcionais; revogação de essencial = fluxo de encerramento de conta.
6. **Ciência contextual**: banner no momento de ativar perfil de extração com IA (informa provedor e que o conteúdo sai do país).
7. **Endpoints**: `GET /api/v1/legal/documents/` (público, versão vigente), `POST /api/v1/legal/consents/`, `GET /api/v1/legal/consents/me/`, `DELETE …/{purpose}/` (revoga opcional).

### 4.4 Direitos do titular (DSR) — art. 18
- Modelo `DataSubjectRequest` (tipo, solicitante, prazo 15 dias, status, responsável, evidência) + eventos `dsr.*`.
- Funções: **exportar meus dados** (JSON/CSV; já parcialmente viável por `GetUserProfileView`), **corrigir**, **eliminar/anonimizar** (cascata consciente: `CustomUser` → `SET_NULL`/anonimização nos logs, **preservando a trilha de auditoria** por obrigação legal/legítimo interesse de segurança, com PII substituída por pseudônimo), **portabilidade**, **revogar consentimento**, **informação sobre compartilhamento**.
- Canal: e-mail do encarregado + formulário autenticado. Titulares **externos** (clientes dos escritórios) → ficam sob o controlador; o Cadrius oferece ferramenta para o escritório localizar/excluir dados de um e-mail/telefone específico (busca por hash determinístico).

---

## 5. Retenção, minimização e proteção do dado

| Dado | Retenção proposta* | Tratamento |
|------|-------------------|-----------|
| `AuditEvent` (segurança/acesso) | **12 meses online + 5 anos arquivo** (Marco Civil art. 15 exige 6 meses p/ registros de acesso a aplicações; LGPD prevê necessidade) | imutável; IP truncado (/24, /48) após 90 dias |
| `EmailMessage.body_text` | configurável por org (padrão 90 dias) após processamento | expurgo/anonimização job; guardar só metadados + resultado da extração |
| `ExecutionLog.trigger_payload/final_result` | 90 dias | mascarar campos PII (`redaction.py`) já na gravação; expurgar payload, manter métrica de ROI |
| `IntegrationLog.request_data/response_body` | 30 dias | idem |
| Contas inativas / org cancelada | 30 dias de graça → eliminação | `retention.purged` |
| Backups | 30 dias, **criptografados**, fora do git | ver abaixo |

\*Valores iniciais — validar com DPO/jurídico; tornar configuráveis por setting.

Ações técnicas associadas:
- **F1 (urgente):** remover `backups/` do índice (`git rm --cached`), adicionar ao `.gitignore`, **reescrever histórico** (`git filter-repo`) e **rotacionar** qualquer segredo contido nos dumps; avaliar se constitui incidente (art. 48) e registrar decisão. Backups só em storage privado, criptografados (age/GPG), restore testado e logado.
- **F3:** criar de fato `core/utils.py` (Fernet, `ENCRYPTION_KEY` obrigatória em produção, suporte a **rotação** com `MultiFernet`), campo `EncryptedJSONField`/`EncryptedCharField`, migração de dados que criptografa credenciais existentes; só então manter a frase no `SECURITY.md`.
- Criptografia de campos sensíveis (CPF) e **hash determinístico** (HMAC) para busca/DSR.
- `ExecutionLog`/`IntegrationLog`: gravar **payload redigido**; payload bruto só em modo debug explícito por org, com TTL curto.
- Corrigir F5 (blacklist), F8 (vincular recursos a `Organization`, resolver tenant explicitamente via header/claim e auditar troca), F10 (sem defaults inseguros em prod: falhar no boot).

---

## 6. Fases, entregáveis e critérios de aceite

> Estimativas em dias de dev focado (1 pessoa). Cada fase termina com PR separado, testes e atualização da ROPA.

### Fase 0 — Contenção (1–2 d) 🔴 *fazer primeiro*
- [ ] Remover/purgar `backups/` do git + rotação de segredos (F1)
- [ ] Sentry: `send_default_pii=False`, sample 0.1, `before_send` scrubber (F2)
- [ ] Corrigir doc/código de criptografia (`core/utils.py` + migração) (F3)
- [ ] Falhar o boot em produção sem `SECRET_KEY`/`ENCRYPTION_KEY`/chaves (F10)

**Aceite:** `git log --all -- backups` sem dumps; Sentry de teste sem IP/e-mail; credenciais ilegíveis em `psql`.

### Fase 1 — Fundação da trilha (4–5 d)
- [ ] App `audit`: `AuditEvent` + hash chain + imutabilidade em nível de banco + admin read-only
- [ ] `AuditContextMiddleware` (request_id, ip, ua, actor, tenant) + `LOGGING` JSON com redação
- [ ] Eventos de **autenticação/sessão** (login ok/falha/lockout/logout/senha/SSO) incl. adapter allauth
- [ ] Ativar `token_blacklist` e logout que revoga (F5)
- [ ] Job de verificação/ancoragem da cadeia de hash

**Aceite:** testes provando que `UPDATE/DELETE` em `AuditEvent` falha com o role da app; cadeia quebrada é detectada; todo login (ok/falha) gera evento com `request_id`.

### Fase 2 — Cobertura de ações e dados (5–6 d)
- [ ] `AuditedMixin` nos ViewSets (mailboxes, emails, workflows, extraction-profiles, tasks, teams, billing)
- [ ] Auditoria do Django Admin (+ justificativa para acesso a dados de cliente) (F9)
- [ ] Eventos de `data.read/export/bulk_read`, `ai.request`, `integration.call`, `message.sent`, webhooks
- [ ] Propagar contexto às tasks Django-Q
- [ ] Redação de payloads em `ExecutionLog/IntegrationLog` (F4) e resolver tenant explícito (F8)
- [ ] API `GET /api/v1/audit/events/` por organização (OWNER/ADMIN) + export CSV (que também gera `audit.export`)

**Aceite:** matriz "endpoint × evento" 100% coberta por teste automatizado; nenhum evento contém PII em claro (teste com fixtures PII + assert de varredura).

### Fase 3 — Termos, consentimento e ROPA (5–7 d, + revisão jurídica em paralelo)
- [ ] Modelos `LegalDocument`, `ConsentRecord`, `SubprocessorEntry` + endpoints
- [ ] Aceite obrigatório no cadastro e no SSO; `428` para reaceite; modal no front
- [ ] DPA/cláusula de controlador na criação da Organization e ao conectar fonte
- [ ] Página pública de suboperadores; aviso de IA contextual
- [ ] `docs/compliance/ROPA.md` (gerado a partir do catálogo `data_categories` + `legal_basis`)

**Aceite:** impossível criar conta sem aceite; consulta "quem aceitou qual versão em que data/IP" em 1 query; hash do texto confere.

### Fase 4 — Detecção de anomalias e monitoramento (5–6 d)
- [ ] `UserActivityBaseline` + `detectors.py` (regras A1–A12) + `AnomalyAlert`
- [ ] Notificações (e-mail/Telegram/Sentry) + triagem no admin de segurança
- [ ] Tela "Atividade da conta" + encerrar sessões; "Auditoria do escritório"
- [ ] Envio dos logs a Loki/ELK (ou Supabase/S3 versionado) + dashboards/alertas (consumo de `AuditEvent` + app logs)

**Aceite:** cenários simulados (viagem impossível, export em massa, enumeração cross-tenant, role escalation) disparam o alerta esperado; falso-positivo medido em 2 semanas de uso real.

### Fase 5 — Direitos do titular, retenção e MFA (6–8 d)
- [ ] `DataSubjectRequest` + exportação/eliminação/anonimização preservando trilha
- [ ] Jobs de retenção/expurgo auditados (`retention.purged`)
- [ ] MFA (TOTP) opcional → obrigatório para OWNER/ADMIN e para staff do Django admin
- [ ] Verificação de e-mail obrigatória (reverter `ACCOUNT_EMAIL_VERIFICATION='none'` de forma segura)

**Aceite:** DSR de teste cumprido de ponta a ponta dentro do SLA de 15 dias simulado; purge remove payloads sem quebrar métricas de ROI.

### Fase 6 — Governança e evidências (contínua; **depende de você/jurídico**)
- [ ] Nomear **Encarregado (DPO)** e publicar canal de contato
- [ ] **RIPD/DPIA** (uso de LLMs com dados processuais é alto risco → obrigatório na prática)
- [ ] Contratos/DPAs com suboperadores; avaliação de transferência internacional (art. 33)
- [ ] Política de segurança da informação, de retenção e de resposta a incidentes (comunicação ANPD/titulares em prazo razoável; ANPD indica 3 dias úteis)
- [ ] Revisão trimestral de acessos (extraída da trilha) e teste anual de restauração de backup
- [ ] Pentest e scan de dependências no CI (`pip-audit`, `bandit`, secret scanning) — CI já existe em `.github/workflows/ci.yml`
- [ ] Escopo de certificação: decidir se o alvo é **ISO 27001 formal** (SGSI, auditoria externa) ou "aderente"; 27701 exige 27001 como base.

---

## 7. Decisões pendentes (preciso de você)

1. **Backups no git (F1):** posso reescrever o histórico (`filter-repo` + force-push) — afeta todos os clones/branches. Esses dumps têm dados reais de clientes, ou só de teste?
2. **Onde guardar a trilha fora do banco:** Supabase Storage (já usado em backup), S3/R2 com Object Lock, ou stack Loki/Grafana no próprio compose? (impacta custo e imutabilidade)
3. **Papel jurídico:** Cadrius como **operador** (padrão proposto) ou também controlador de parte dos dados? Define redação dos termos e do DPA.
4. **Quem é o encarregado/DPO** e qual e-mail público de privacidade?
5. **Retenção:** aceita os prazos da seção 5 como ponto de partida?
6. **Meta de certificação:** ISO 27001 formal agora ou "preparar evidências" primeiro?
7. **Frontend (React) está neste repo?** Não está — preciso saber quem/onde implementa modal de aceite, tela de privacidade e "Atividade da conta" (o backend entrega os endpoints; contrato documentado no OpenAPI via drf-spectacular).

---

## 8. Riscos do próprio plano
- **Volume**: `data.read` em toda listagem pode gerar milhões de linhas → registrar leitura **de detalhe** e **agregada por listagem** (1 evento por request, com contagem), amostrar o resto; particionar desde o início.
- **Performance**: gravação assíncrona + contextvars cuidadosamente propagados; teste de carga antes de ativar em produção.
- **Falso senso de conformidade**: código sem DPO, RIPD e contratos **não** é conformidade — a Fase 6 é tão importante quanto as demais.
- **Anonimização vs. trilha**: eliminação de dados não pode apagar a prova de segurança; documentar a base legal da manutenção (art. 16, I e II; art. 7º, IX).
- **Aviso:** este documento é engenharia/segurança, **não** parecer jurídico; prazos e bases legais citados devem ser validados por advogado especializado em proteção de dados.
