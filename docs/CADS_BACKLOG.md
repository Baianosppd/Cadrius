# Cards (CAD) — entregues e pendentes

Formato: `CAD-0XX: Task - título` · **Área** · **Branch** · itens com critério de aceite. ✅ = entregue na branch indicada.
Ordem de merge sugerida: `CAD-056 → 057 → 058 → 059 → 065 → 066 → 067 → 068 → 069 → 070 → 071` (as branches são empilhadas; cada uma contém as anteriores).

## A. Entregues

| CAD | Título | Branch | Resumo |
|---|---|---|---|
| CAD-056 | Sentry com `environment`/`release` + contexto de usuário e escritório | `CAD-056` | Back ✅; **React pendente** (CAD-096) |
| CAD-057 | Proteger Dozzle com BasicAuth/Traefik; remover porta 8888 | `CAD-057` | ✅ |
| CAD-058 | Rotação de logs (`max-size`) e runbook de alerta Sentry | `CAD-058` | ✅ (regra no painel do Sentry é manual) |
| CAD-059 | Logging estruturado com `execution_log_id` | `CAD-059` | ✅ |
| CAD-064 | Plano de trilha de auditoria / termos de ciência (LGPD/ISO) | `CAD-064` | ✅ (doc) |
| CAD-065 | Blindagem pós-auditoria de segurança | `CAD-065` | ✅ (ver `docs/AUDITORIA_SEGURANCA.md`) |
| CAD-066 | DevSecOps e correção de defeitos (Docker, CI/CD, dependências, SSO, workflows) | `CAD-066` | ✅ + integra isolamento multi-tenant |
| CAD-067 | Trilha de auditoria imutável + detecção de anomalias | `CAD-067` | ✅ |
| CAD-068 | LGPD: termos, consentimento, DSR e retenção | `CAD-068` | ✅ (textos: revisão jurídica) |
| CAD-069 | Governança da IA autônoma (humano no circuito, kill switch) | `CAD-069` | ✅ |
| CAD-070 | Centro de Segurança (telas) + conformidade ISO 27001/27701/LGPD + RoPA | `CAD-070` | ✅ |
| CAD-071 | Análise do projeto, plano por equipe, backlog e eventos de comunicação (RNE-011) | `CAD-071` | ✅ |

## B. Back-end (Thales)

**CAD-072: Task - API de conexões/integrações (cofre de credenciais)** · RF-019
* CRUD `/api/v1/connections/` isolado por escritório; `credentials` **write-only** (nunca devolvidas; mostrar só `has_credentials` e últimos 4 caracteres do token).
* Testar conexão (`POST …/{id}/test/`) com timeout e SSRF-guard; auditar `connection.created|updated|deleted`.
* Aceite: teste de vazamento entre escritórios; credencial nunca aparece em resposta, log ou Sentry.

**CAD-073: Task - API de Organização e cadastro completo** · RF-001, RF-005
* `GET/PATCH /api/v1/organization/` (OWNER/ADMIN) com CNPJ validado (dígitos), razão social, regime, endereço; criar escritório no wizard "Empresa" (OWNER automático).
* Registro aceita `oab_number`, `oab_uf`, `practice_area`; `oab_uf`/`practice_area` editáveis no perfil.
* Aceite: validação de CNPJ/CPF/UF; plano inicial FREE; evento `org.updated`.

**CAD-074: Task - Upload e extração de documentos (PDF/imagem)** · RF-009, RF-010
* `POST /api/v1/documents/` (multipart; PDF/PNG/JPG; ≤ 10 MB; validação de *magic bytes*; antivírus ClamAV opcional), vínculo à organização, status Pendente→Processando→Concluído/Falhou (RF-011).
* Extração via fila (OCR/`pypdf` + IA sob `run_guarded`), resultado revisável (RF-026).
* Aceite: arquivos fora de `media/` público; URL assinada; retenção; teste de tenant.

**CAD-075: Task - Despacho de e-mails para workflows + reprocessamento (CRÍTICO)** · RF-027, RNE-009
* Após `fetch_emails`, enfileirar `process_email` para cada `EmailMessage` não despachado, usando o **perfil de extração e workflow** vinculados à caixa (criar o vínculo `MailBox → ExtractionProfile + Workflow`, previsto no documento como `AutomationRule`).
* Job de reprocessamento de `ExecutionLog` `PENDING` > N minutos (idempotente).
* Aceite: e-mail novo → execução registrada sem intervenção; broker fora do ar não perde payload; teste E2E com IMAP simulado.

**CAD-076: Task - Deduplicação de disparos (1 minuto)** · RNE-014
* Chave de deduplicação (`workflow_id + hash(payload)`) com TTL de 60 s (Redis) configurável por workflow.
* Aceite: mesmo webhook/e-mail duas vezes em 60 s dispara 1 execução; log `duplicate_ignored`.

**CAD-077: Task - Avaliação de gatilhos (condições) e Data Mapper** · RF-017, RF-018, RNE-017
* Condições no `Trigger` (ex.: assunto contém, remetente, campo JSON `==`/`in`), avaliadas antes de executar; descarte silencioso registrado.
* Aplicar `payload_mapping` (renomear/filtrar campos) antes do template.
* Aceite: testes por operador; payload só com campos mapeados chega à ação.

**CAD-078: Task - Biblioteca de templates base de workflows** · RNE-018 — templates jurídicos genéricos adaptáveis ao `practice_area`; criação sempre como rascunho (CAD-069).

**CAD-079: Task - Assinatura HMAC em webhooks** · RF-016
* `Trigger.webhook_secret` (cifrado); validar `X-Cadrius-Signature` (HMAC-SHA256 + timestamp, janela de 5 min); Evolution inbound autenticado (`apikey` da instância).
* Aceite: requisição sem/ com assinatura inválida → 401 + evento `webhook.invalid_token`; *replay* recusado.

**CAD-080: Task - E-mail transacional e `EmailLog`** · RF-020, RF-021
* Implementar `EMAIL_SMTP` (backend SMTP por org/conexão, templates), `EmailLog` com status SENT/DELIVERED/BOUNCED (webhook do provedor) e evento `message.sent`.
* Aceite: bounce atualiza o status; destinatário nunca em log/trilha.

**CAD-081: Task - Ação "Criar tarefa" nos workflows** · RF-028 — novo `ActionType.CREATE_TASK` criando `UserTask` para membro do escritório (validação de tenant).

**CAD-082: Task - Medição de desempenho (p95 < 200 ms) e teste de carga** · RNF-004 — `django-silk`/métricas Prometheus ou `Server-Timing`; Locust nos endpoints CRUD; falha no CI se p95 > 200 ms em ambiente de teste.

**CAD-086: Task - Limpeza de dívida técnica** — remover/arrumar `integrations/telegram.py` (atributo inexistente), `billing/middleware.py`, app `webhooks` duplicado (rota `<uuid>` inalcançável), `IntegrationConfig/IntegrationLog` legados em `tasks`; manter migrações.
**CAD-087: Task - Cota de IA unificada** — um único serviço (`check_and_update_quota`), status `QUOTA_EXCEEDED` válido em `ExecutionLog`, incremento só quando a execução ocorre.
**CAD-088: Task - Criptografar `ExecutionLog.trigger_payload`/`final_result`** — `EncryptedJSONField` + migração; manter retenção de 90 dias.

**CAD-103: Task - Contrato OpenAPI completo para o front** · `drf-spectacular` hoje emite ~70 avisos: os `APIView` sem `serializer_class` ficam sem schema de request/response em `/api/docs/`. Adicionar `@extend_schema` (request/response/erros 400/403/428/429) em auth, billing, audit, privacy, aigov e security; falhar o CI se `manage.py spectacular --validate` tiver erros. Aceite: Ryan gera o cliente TypeScript a partir do schema sem ajustes manuais.

**CAD-090: Task - API de escrita do Centro de Segurança e atividade da conta** (para o React)
* `GET /api/v1/security/events/` (trilha global, staff), `POST /security/audit/verify/`, `PATCH /security/alerts/{id}/`, `POST /security/controls/{framework}/{id}/assess/`,
  `POST /security/ai/switch/`, `GET /security/privacy/`, `GET /security/controls/{framework}/export/` (CSV).
* `GET /api/v1/audit/me/` (meus logins/ações) e `GET/DELETE /api/v1/auth/sessions/` (listar/encerrar sessões) para a tela "Atividade da conta".
* Aceite: mesmos controles de permissão e auditoria das telas HTML; testes de 403 para não-staff.

## C. Front-end (Ryan) — detalhes em `docs/PLANO_EQUIPES.md` §1

**CAD-091: Task - Aceite de termos no cadastro/SSO e modal de reaceite (428)** · **CAD-092: Task - Tela Privacidade e dados (aceites, exportação, pedidos, encerramento)**
**CAD-093: Task - Auditoria do escritório (trilha, resumo, CSV, alertas)** · **CAD-094: Task - IA segura (gerar rascunho, aprovar/rejeitar, fila de confirmação, política, atividade)**
**CAD-095: Task - Centro de Segurança em React (visão geral, normas, postura, RoPA, IA, privacidade)** · **CAD-096: Task - Sentry no React** (`@sentry/react`, `VITE_SENTRY_DSN`, `setUser({id})`, tag `organization_id`)

## D. Design (Allan) — detalhes em `docs/PLANO_EQUIPES.md` §2

**CAD-097: Task - Design System de segurança** (tokens, pills, anel de pontuação, tabelas, banners, diálogos destrutivos)
**CAD-098: Task - Fluxos LGPD e IA** (cadastro/reaceite, pedido do titular, encerramento, rascunho→aprovação→confirmação) com microcopy revisada pelo jurídico
**CAD-099: Task - Telas do Centro de Segurança** (desktop e mobile, estados vazios/erro) e teste de usabilidade com 5 advogados

## E. DevSecOps (Jullio)

**CAD-083: Task - MFA (TOTP) e endurecimento do Admin** · obrigatório para OWNER/ADMIN e staff; `/admin/` atrás de caminho não óbvio/IP allowlist no Traefik; reautenticação para ações sensíveis (kill switch, exportações).
**CAD-084: Task - Verificação de e-mail** (`ACCOUNT_EMAIL_VERIFICATION='mandatory'`) com fluxo de reenvio e limite de taxa — depende do CAD-080.
**CAD-085: Task - `docker-socket-proxy` para Traefik/Dozzle** (permissões mínimas, rede interna).
**CAD-089: Task - Monitoramento externo e teste trimestral de restauração** (uptime em `/readyz/`, alerta Discord/Telegram, restauração em staging com evidência anexada ao controle ISO A.8.13).
**CAD-100: Task - Saneamento do histórico do git e rotação de segredos** (⛔ manual): `git filter-repo` (senha Gmail, dumps), revogar/rotacionar, ativar *secret scanning* e *push protection* no GitHub e tornar o job `gitleaks` **bloqueante**.
**CAD-101: Task - Jurídico/Governança**: nomear encarregado (DPO), revisar e publicar os 4 documentos (v1.0), assinar DPAs com suboperadores (marcar `contract_verified`), preencher RIPD (`docs/RIPD_MODELO.md`), política de resposta a incidentes aprovada pela direção.
