# Plano de evolução do produto — Cadrius como "sistema operacional" do escritório

> Autor: DevSecOps/Tech Lead · Data: 2026-10-04 · Base: código em `main` (back) e `cadrius---front-end` (front)
> Este plano **não altera código**. Cada item vira um card `CAD-1xx` (tabela da §12) e entra em `docs/CADS_BACKLOG.md`.
> Itens marcados **[DECISÃO]** precisam de resposta do Jullio/diretoria antes de começar (custos, contratos, jurídico).
> Itens marcados **[VALIDAR]** dependem de documentação/contrato de terceiros que deve ser conferido na hora de implementar (APIs mudam).

---

## 0. Onde estamos (fatos do código, não suposições)

| Tema | Hoje |
|---|---|
| Cifra em repouso | `core/utils.py` tem `EncryptedTextField`/`EncryptedJSONField` (Fernet, `MultiFernet` com rotação `ENCRYPTION_KEY="nova,antiga"`, prefixo `enc::` p/ migração gradual). **Só** credenciais de integrações (`AppConnection.credentials`) e senha IMAP usam. |
| Dados pessoais no banco | **Em claro**: `CustomUser` (`email`, `phone`, `cpf` único, `oab_number`, `oab_uf`, `practice_area`, nome), `Organization` (`cnpj` único, endereço, telefones, e-mail), `ClientDocument.nome_cliente`, `ConsentRecord.ip`, arquivos de `documents/` (FileField em disco). |
| IA | `aigov/`: política por escritório (`off / suggest / supervised / autonomous_limited`), kill switch por escritório e global, `run_guarded()`, log `AIActionLog` sem conteúdo, `sanitize.py` (anti-prompt-injection). `extraction/` tem `ai_wrapper` (OpenAI/Groq/Gemini) e schemas (`ProcessoJuridicoSchema`, `ServiceOrderSchema`). Workflows gerados por IA nascem como **rascunho** (`ai_generated`, `approved_by`). |
| Execução | `workflows/` (Trigger → Actions: webhook, WhatsApp/Evolution, Telegram, Trello, Sheets…) com Django-Q2 + Redis. `integrations/AppConnection` já tem `ASTREA` como opção (sem conector real). |
| Agenda | `tasks.Task` tem `scheduled_at`, `responsavel`, `sincronizar` (flag **sem** integração por trás). `allauth` já tem o provider Google habilitado só para login. |
| Documentos | `documents.Document` (upload, tipo, status). Sem OCR, sem extração automática ligada ao upload, sem antivírus, sem versionamento. |
| Backups | `pg_dump → GPG → retenção local → rclone` já implementado (`deploy/scripts/backup.sh`); **offsite não configurado** (`offsite=false` no status). |
| SSO | `/api/v1/auth/google|microsoft/` **não existem** no back (CAD-105). Front já tem botão e `GoogleCallback.jsx`. |
| Cadastro | Fluxo em etapas (`RegisterIndividual`, `RegisterEmpresa`, `steps/`). Recarregar a página perde o que foi digitado. |
| Produção | No ar em `app.` / `api.cadrius.ia.br`, TLS Let's Encrypt real, CSP, backup pré-deploy, Dozzle, Centro de Segurança. **Sem plano ativo cadastrado** (cadastro de escritório falha). |

---

## 1. Princípios (valem para tudo abaixo)

1. **Advogado decide o que importa.** A IA propõe, prepara e executa só o que é reversível/baixo impacto e foi explicitamente liberado (§8).
2. **Dado do escritório é do escritório.** Nada de um cliente entra no contexto de outro; nada é usado para treinar modelo de terceiros; tudo isolado por `organization_id`.
3. **Minimizar antes de enviar.** O que vai para provedor de IA/terceiro passa por mascaramento (CPF, telefone, e-mail, nº de processo quando não for necessário) — `aigov/sanitize.py` é o ponto de extensão.
4. **Tudo auditado.** Cada leitura de dado pessoal sensível, chamada de IA, decisão automática e sincronização externa gera evento na trilha (`audit.service.log`).
5. **Falhar fechado.** Sem chave, sem consentimento, sem política que permita → bloqueia (como `aigov.guard` já faz).
6. **Entrega incremental.** Cada fase termina com algo usável em produção e coberto por smoke-test (`deploy/scripts/smoke-test.sh`).

---

## 2. Criptografia dos dados pessoais (prioridade P0)

### 2.1 Escopo — o que é dado pessoal hoje

| Modelo | Campos | Classe | Estratégia |
|---|---|---|---|
| `CustomUser` | `cpf`, `phone`, `oab_number`, `oab_uf`, `first_name`, `last_name` | pessoal (LGPD art. 5º I) | **cifra de campo + índice cego** (onde há busca/unicidade) |
| `CustomUser` | `email`, `username` | pessoal **e** identificador de login | ver 2.3 (decisão) |
| `Organization` | `cnpj`, `razao_social`, endereço (`cep`, `street`, `number`, `neighborhood`, `city`), `main_phone`, `corporate_phone`, `corporate_email` | dado de PJ/contato (pessoal quando MEI/sócio) | cifra de campo + índice cego (`cnpj` único) |
| `ClientDocument` | `nome_cliente` | pessoal de terceiros (clientes do escritório) | cifra de campo |
| `Document.arquivo` | conteúdo dos arquivos (peças, contratos, RG/CPF digitalizados) | pode conter dado sensível | **cifra do arquivo** (Fernet em streaming/chunks ou `age`), chave por escritório |
| `ConsentRecord` | `ip` | pessoal | já hash do user-agent; cifrar/truncar IP |
| `PrivacyRequest` | texto livre do titular | pessoal | cifra de campo |
| `AppConnection.credentials`, senha IMAP | segredos | já cifrados | manter |
| `AuditEvent` | `changes`, `actor_ref` | já redigido por `audit.redaction` | manter; revisar para garantir que nada novo vaze |
| Logs / Sentry | — | — | já sem PII automática; revisar após cada integração |

### 2.2 Arquitetura

* **Chaves.** Hoje: uma `ENCRYPTION_KEY` (Fernet). Evoluir para **envelope**: `KEK` (no `.env` do servidor, rotacionável) cifra **DEKs** por escritório guardadas no banco (`OrgKey`). Benefícios: rotação barata (re-embrulha DEKs, não re-cifra tudo), *crypto-shredding* (apagar a DEK do escritório = eliminação irreversível, ótimo p/ direito de eliminação LGPD art. 18 VI).
* **Índice cego.** Para `cpf`/`cnpj`/e-mail precisa de busca exata e unicidade sem decifrar tudo: coluna `*_bidx = HMAC-SHA256(chave_bidx, valor_normalizado)`; `unique=True` passa a ser no `*_bidx`. A `chave_bidx` é **separada** da chave de cifra e nunca rotaciona sem reindexar.
* **Campo.** Estender `core.utils.EncryptedTextField` (já existe) com: normalização, prefixo de versão (`enc::v2::<key_id>::…`) e `blind_index=` opcional. Compatível com legado em texto puro durante a migração (já suportado pelo prefixo).
* **Migração em 3 passos sem downtime:** (1) *expand*: adicionar colunas `*_enc`/`*_bidx` e gravar nos dois lugares; (2) *backfill*: `manage.py encrypt_pii --batch 500 --org <id>` idempotente, com contagem e auditoria; (3) *contract*: leitura só da coluna cifrada, remover coluna clara em release posterior após backup verificado.
* **Busca/ordenação.** Cifrado não ordena nem faz `LIKE`. Telas que buscam por nome (ex.: lista de clientes) usam **tokens normalizados** com índice cego por prefixo/trigrama **[DECISÃO: aceitar a perda de busca parcial em nome ou manter nome em claro e cifrar só documentos/contato]**.
* **Arquivos.** `EncryptedFileStorage` (storage do Django) que cifra no `save()` e decifra no `open()`; tamanho máximo/streaming para não estourar memória (hoje o backup cifra em memória — limite já documentado em `backup_to_supabase.py`). Antivírus **antes** de cifrar.
* **Em trânsito/descanso complementar:** TLS 1.2+ já ativo; Postgres só em `db_net` (já); criptografia de volume (LUKS) do VPS **[VALIDAR com Locaweb]**; backups já GPG.

### 2.3 O caso do e-mail (identificador de login) **[DECISÃO]**

O Django autentica por `username`/`email`. Opções:
* **A (recomendada para a fase 1):** manter e-mail/username em claro **mas** proteger com: acesso mínimo ao banco (papéis já separados), backups cifrados, volume cifrado, e minimização nos logs. Cifrar tudo o mais.
* **B (fase posterior):** backend de autenticação próprio que localiza usuário por `email_bidx` e guarda o e-mail cifrado; exige reescrever `allauth`/SSO/recuperação de senha. Alto custo, risco de regressão; só se exigência contratual/regulatória pedir.

### 2.4 Critérios de aceite

* `SELECT cpf, phone, oab_number FROM accounts_customuser` em produção devolve só `enc::…`.
* Login, cadastro, SSO, convite de membro e telas de equipe/perfil continuam funcionando; suíte de testes inclui **teste de que o valor em disco ≠ valor em claro**.
* Rotação de chave testada em staging (`ENCRYPTION_KEY="nova,antiga"` → `rotate_encryption` → remover antiga) e *crypto-shredding* de um escritório de teste.
* Check novo no Centro de Segurança: `pii_encrypted` (amostra de linhas em claro = 0). Atualizar RoPA (`compliance/ropa.py`) e `docs/RIPD_MODELO.md`.
* Documentar procedimento de perda de chave (é irrecuperável: **backup da KEK fora do servidor**, em cofre, com dupla custódia).

### 2.5 Riscos
Perda da chave = perda dos dados → backup da KEK + teste de restauração; backfill longo → por lotes e fora do horário; desempenho de busca → índices cegos; erro de normalização (CPF com/sem pontos) → normalizar sempre antes de HMAC.

---

## 3. Correções P0 antes de abrir para usuários reais

| Card | O quê | Detalhe |
|---|---|---|
| **CAD-119** | Plano pago só depois do pagamento | Hoje o cadastro atribui o plano na hora. Fluxo: cadastro → plano **FREE/trial** → Stripe Checkout → webhook `checkout.session.completed` (assinatura verificada) → atribui plano. **[DECISÃO]** planos, preços, limites, trial, política de inadimplência. Em produção ainda **não há plano ativo**: criar pelo admin (Billing → Subscription plans) ou comando `seed_plans` versionado. |
| **CAD-121** | 503 (não 500) quando Redis/broker cair | `ai/executions/<id>/review/` e demais pontos que enfileiram: capturar erro de broker, devolver 503 com `Retry-After` e mensagem clara; `readyz` já mostra `cache`. |
| **CAD-115** | Recuperação de senha por e-mail | Token de uso único, expira em 1 h, resposta idêntica exista ou não o e-mail (anti-enumeração), throttle, auditoria, e-mail transacional (SMTP/SES — ver §3.1). |
| **CAD-105** | SSO Google/Microsoft | Ver §6. |
| **CAD-150** | Cadastro não perde dados ao recarregar | Ver §3.2. |

### 3.1 E-mail transacional **[DECISÃO]**
Necessário para recuperação de senha, convites, avisos de prazo, verificação de e-mail. Opções: Amazon SES, Brevo, Mailgun, Locaweb SMTP. Configurar **SPF, DKIM, DMARC** no DNS de `cadrius.ia.br`; remetente `no-reply@`; Django `EMAIL_*` via `.env` do servidor; template versionado. Em staging, capturar e-mails (Mailpit) em vez de enviar.

### 3.2 Cadastro sem perda de dados (front)
* Persistir o rascunho a cada mudança de etapa/campo (debounce) em `sessionStorage` (some ao fechar a aba) com **TTL de 24 h** e chave versionada; limpar após sucesso.
* **Nunca** persistir: senha, confirmação de senha, tokens. **[DECISÃO]** CPF/telefone no rascunho local: recomendo **não** persistir CPF; persistir só nome, e-mail, tipo de conta, etapa atual.
* `beforeunload` avisando quando há dados não salvos; restaurar etapa/URL com `react-router` (`?etapa=3`), não só estado em memória.
* Erros 400 do back mantêm o formulário preenchido e mostram erro no campo (hoje alguns caminhos limpam).
* Teste Vitest: preencher → recarregar → restaura; senha **não** restaura. Atualizar `docs/PLANO_FRONT_END.md`.

---

## 4. Backups para fora do servidor (CAD-151)

Já existe `pg_dump → GPG → rclone`. Falta **destino** e **prova de restauração**.

1. **Escolher destino [DECISÃO]**: Backblaze B2 (barato, S3-compatível, Object Lock), Wasabi, AWS S3 (Glacier IR), ou Locaweb Objetos. Critérios: região (BR/AWS sa-east-1 por LGPD), **versionamento + Object Lock (WORM)** contra ransomware, custo, DPA assinado (suboperador — registrar em `privacy.Subprocessor`).
2. **Conta e credencial de menor privilégio**: chave **só de escrita** (sem delete/list de objetos antigos) para o servidor; chave de leitura separada, guardada fora do servidor.
3. Servidor: `rclone config` (remote `cadrius-offsite`), `RCLONE_REMOTE=cadrius-offsite:cadrius-backups` em `/etc/cadrius/backup.env`; `backup.sh prod manual` e checar `offsite=true` no `backup.status` (o smoke-test e o check `backup` do Centro de Segurança passam a PASS).
4. **Retenção em camadas**: diário 14, semanal 8, mensal 12 (lifecycle no bucket); local 7 dias.
5. **Chave GPG**: gerar novo par **fora** do servidor (a anterior foi exposta no chat → revogar e substituir); servidor guarda só a pública; privada em cofre (2 cópias, 2 pessoas).
6. **Drill de restauração trimestral** (`deploy/scripts/restore-test.sh`): baixar → decifrar → restaurar em banco descartável → conferir contagem de tabelas e `verify_audit_chain` → registrar resultado. Backup sem restauração testada **não conta**.
7. Alertas: backup > 26 h ou `offsite=false` → falha visível no Centro de Segurança e (CAD-155) e-mail/WhatsApp para Jullio.
8. Incluir **arquivos de `media/`** (documentos dos clientes) — hoje o dump cobre só o banco: `rclone sync` cifrado (crypt) do volume de mídia.

---

## 5. Leitura de documentos e extração de dados (CAD-160…164)

### 5.1 Pipeline
```
upload → antivírus (ClamAV) → valida tipo por conteúdo (python-magic) → cifra e guarda
      → OCR (se imagem/PDF escaneado) → texto → classificação do tipo → extração estruturada (IA) 
      → score de confiança → fila de revisão (advogado) → dados confirmados viram campos/tarefas/prazos
```
Tudo assíncrono (Django-Q2), com status visível no front (`PENDENTE → PROCESSANDO → REVISAR → CONFIRMADO / FALHA`).

### 5.2 Componentes
* **Antivírus:** container `clamav` na rede interna; rejeita antes de gravar (CAD-122).
* **OCR:** `ocrmypdf` + Tesseract (`por`) em container **worker de documentos** separado (CPU pesada, limites de memória) **[alternativa paga: Google Document AI / AWS Textract — melhor em manuscrito, mas é suboperador com dado do cliente → DPA]**.
* **Classificação e extração:** reaproveitar `extraction/` (`ProcessoJuridicoSchema` etc.). Novos schemas: procuração, contrato, petição, sentença/acórdão, intimação/citação, RG/CPF/comprovante, guia/custas. Prompts com `wrap_untrusted()` (documento é entrada não confiável — prompt injection).
* **Saídas úteis:** número CNJ, partes, vara/tribunal, classe, valor da causa, **prazos** (com regra de contagem: dias úteis/corridos, feriados forenses) → criam `Task`/evento de agenda **como rascunho para confirmação**.
* **Confiança e revisão:** cada campo vem com `confidence`; < limiar → destaque amarelo; nunca grava como "fato" sem confirmação até o escritório subir o nível de autonomia (§8).
* **Mascaramento antes da IA:** substituir CPF/RG/telefone por *placeholders* quando o campo não for necessário à tarefa; reidratar depois.
* **Custos/limites:** `daily_ai_request_limit` por escritório (já existe) + limite de páginas/mês por plano.

### 5.3 Front
Tela de documento com visualizador (`react-pdf`), painel lateral com campos extraídos (editáveis), botão Confirmar/Corrigir, histórico de versões. Correção do usuário vira **sinal de aprendizado** (§8).

---

## 6. Integrações — passo a passo

### 6.1 SSO Google e Microsoft (CAD-105)
**Back (Thales):** `allauth` já tem o provider Google. Implementar `POST /api/v1/auth/google/` e `/microsoft/`: o front envia o `id_token`/`code`; o back **valida assinatura, `aud`, `iss`, `exp` e `email_verified`**, vincula/cria usuário conforme `accounts.adapters.B2BSocialAccountAdapter` (só vincula a escritório com e-mail verificado — check `sso_verified_email` já existe), devolve JWT (SimpleJWT), respeita **428** (termos pendentes) e registra auditoria `auth.sso_login`. Throttle e *state/nonce* anti-CSRF/replay.

**Google Cloud (Jullio):**
1. console.cloud.google.com → novo projeto "Cadrius" → *APIs & Services → OAuth consent screen* → tipo **External**, nome, logo, domínio `cadrius.ia.br`, links de política/termos (já publicados), e-mail de suporte.
2. Escopos: `openid email profile` (não sensíveis → publicação sem verificação demorada).
3. *Credentials → Create OAuth client ID → Web application*. **Origens JS autorizadas:** `https://app.cadrius.ia.br`, `https://app-teste.cadrius.ia.br`. **URIs de redirecionamento:** as rotas do back/front definidas (`https://app.cadrius.ia.br/auth/google/callback`, idem teste).
4. Guardar `GOOGLE_CLIENT_ID` (público → build do front `VITE_GOOGLE_CLIENT_ID`) e `GOOGLE_CLIENT_SECRET` (só no `.env` do back no servidor).
5. Um client **por ambiente** (teste ≠ produção).

**Microsoft (Entra ID):** portal.azure.com → *Microsoft Entra ID → App registrations → New* → "Contas em qualquer diretório organizacional e contas pessoais" → Redirect URI (Web) → *Certificates & secrets → New client secret* (validade ≤ 24 meses, **agendar renovação**) → permissões delegadas `openid email profile User.Read`. Guardar `MICROSOFT_CLIENT_ID/SECRET/TENANT=common`.

**Ativação:** `FRONT_SSO_ENABLED=true` no `.env` do servidor → rebuild do front (`VITE_SSO_ENABLED`); testar em staging; smoke-test ganha checagem de rota SSO.

### 6.2 Google Calendar (CAD-165…168) — foco em **atividades/prazos**
**Modelo:** cada `Task` com `sincronizar=True` vira evento no calendário do responsável; mudanças voltam (bidirecional).

1. **OAuth por usuário** (não por escritório): escopo mínimo `https://www.googleapis.com/auth/calendar.events` (+ `calendar.readonly` p/ listar calendários). **Escopo sensível → exige verificação do app pelo Google** (vídeo, política de privacidade, justificativa) — leva semanas. Enquanto isso, app em *Testing* (máx. 100 usuários de teste) serve para piloto **[DECISÃO: iniciar a verificação já]**.
2. **Tokens:** `access_token` + `refresh_token` guardados em `AppConnection.credentials` (já cifrado). Renovação automática; revogação detectada (`invalid_grant`) marca a conexão como "reconectar" e avisa o usuário.
3. **Mapeamento:** `Task.titulo → summary`, `descricao → description`, `scheduled_at → start/end` (duração padrão configurável), `priority → colorId`, link de volta para o Cadrius; `extendedProperties.private.cadrius_task_id` para casar os dois lados sem duplicar.
4. **Sincronização:** (a) push imediato ao criar/editar/concluir/excluir tarefa (Django-Q); (b) pull via **Push Notifications (`events.watch`)** com canal por usuário (renovar antes de expirar) + `syncToken` incremental; fallback a cada 15 min se o webhook falhar. **Conflito:** vence a última modificação (`updated`), registrando em `sync-history` (tela já existe).
5. **Prazos processuais:** eventos criados pela IA a partir de documentos/publicações entram **como "provisório"** até o advogado confirmar (§8); lembretes (e-mail/pop-up e WhatsApp) em D-5, D-2, D-0; exceção de feriados forenses por tribunal.
6. **Privacidade:** o evento no Google **não** leva dado sensível por padrão (usa título genérico "Prazo — Proc. final 1234" configurável); LGPD: Google é suboperador → registrar.
7. **Aceite:** criar tarefa no Cadrius → aparece no Google em ≤ 1 min; mover no Google → atualiza no Cadrius; revogar acesso → conexão marcada, sem erro 500.
8. Front: tela Integrações → "Conectar Google Calendar", escolha do calendário, status de sincronização, botão Desconectar (apaga tokens e para `watch`).

### 6.3 Integração com ERPs/sistemas jurídicos — "parametrização" (CAD-190…193)
Em vez de um conector fixo por produto, construir um **framework de conectores declarativos**:

```yaml
connector: advbox            # exemplo ilustrativo
auth:   { type: api_key, header: Authorization, prefix: "Bearer " }
base_url: https://…          # configurado por escritório
rate_limit: { rps: 2 }
resources:
  processo:  { list: GET /processos, get: GET /processos/{id}, create: POST /processos }
  cliente:   { list: GET /clientes,  create: POST /clientes }
  andamento: { create: POST /processos/{id}/andamentos }
mapping:                      # campo Cadrius ↔ campo do ERP
  processo.numero_cnj: numeroProcesso
actions:                      # o que a IA/automação pode disparar
  - name: criar_andamento      risk: low   requires_approval: false
  - name: protocolar_peticao   risk: high  requires_approval: true
```
* **Tela "Parametrizar conexão"** (Ryan/Allan): escolher conector → credenciais (cifradas) → **testar conexão** → mapear campos (arrastar e soltar, valores padrão) → escolher o que sincroniza (somente leitura / leitura+escrita) → frequência.
* **Executor** reutiliza `workflows` (Action `ERP_ACTION`) com: tempo limite, *retry* com *backoff*, idempotência (`Idempotency-Key`), proteção SSRF (`integrations/ssrf.py` já existe), auditoria de cada chamada, **modo simulação** (dry-run) para validar antes de escrever.
* **Ordem sugerida [DECISÃO — depende de qual ERP os escritórios-alvo usam]:** 1º **Astrea** (já listado), depois os mais comuns do mercado (Advbox, Projuris, Legal One/Thomson Reuters, CPJ, Themis/Aurum, Jurimetria…). **[VALIDAR]** cada fornecedor: existência de API pública, autenticação, limites, contrato de parceria; alguns só oferecem exportação/CSV ou parceria comercial.
* **Fallback sem API:** importação por planilha/CSV mapeada e, só quando contratualmente permitido, automação de interface (RPA) — **risco jurídico/ToS**, não é o caminho padrão.
* Cada ação com **classe de risco** que alimenta a tabela de autonomia (§8). Ações irreversíveis ou com efeito externo ao cliente (protocolar, excluir, enviar mensagem ao cliente, lançar honorário) **sempre** exigem aprovação humana.

### 6.4 Outras integrações já previstas
WhatsApp (Evolution/Meta) para atendimento e lembretes; Telegram; Trello/ClickUp; Sheets. Revisar chave padrão da Evolution (rotacionar se for a default).

---

## 7. Pesquisa jurídica, notícias e Jusbrasil (CAD-170…176)

### 7.1 Arquitetura: um **hub de fontes** com provedores plugáveis
```
Provider (interface):  search(query, filtros) · fetch(id) · subscribe(termo/processo) · health()
        ├─ DataJud (CNJ)                  → metadados de processos por número/classe/tribunal
        ├─ DJEN / Comunica PJe (CNJ)      → comunicações/intimações/publicações por OAB/nome/processo  [VALIDAR]
        ├─ Diários oficiais / DOU         → publicações (INLABS/Imprensa Nacional)                     [VALIDAR]
        ├─ Tribunais superiores           → STF, STJ, TST: jurisprudência/notícias (feeds/APIs públicas) [VALIDAR]
        ├─ LexML / Planalto               → legislação e normas
        ├─ Notícias (RSS autorizados)     → Conjur, Migalhas, STF/STJ/CNJ/TST, portais de tribunais
        └─ Jusbrasil                      → via contrato/API comercial (ver 7.3)
```
Cada provider: cache (Redis) com TTL por tipo, *rate limit*, circuit breaker, e **log de uso por escritório** (custo/limite por plano).

### 7.2 Funcionalidades
1. **Monitoramento de processos** (cadastrar nº CNJ → acompanhar andamentos → alerta ao advogado responsável). Fonte base: DataJud (público, cobre metadados e movimentações; não traz o inteiro teor) + DJEN para intimações. Deduplicação por hash do andamento.
2. **Captura de intimações/publicações por OAB** (nome/OAB do advogado cadastrado — já temos `oab_number/oab_uf`): fila "Publicações novas" → IA resume e **propõe prazo** (rascunho; §8) → advogado confirma → vira tarefa + evento no Google Calendar.
3. **Pesquisa jurisprudencial** com filtros (tribunal, órgão julgador, data, tese) e **resumo por IA com citação obrigatória da fonte e link** (sem citação, não exibe como fato; evitar "alucinação" de precedentes — regra de produto: *a IA nunca inventa número de processo/ementa*; só reproduz o que veio da fonte).
4. **Notícias e clipping** por área de atuação (`practice_area`) e por cliente/tema: feed diário, resumo, "salvar no processo".
5. **Legislação** consolidada e alertas de mudança em normas seguidas.
6. **Busca unificada** ("ctrl+K") sobre: documentos do escritório, processos, clientes, tarefas **e** fontes externas, respeitando permissões.

### 7.3 Jusbrasil **[DECISÃO + VALIDAR]**
* O Jusbrasil oferece produtos comerciais (assinatura e soluções para empresas/escritórios). **Não assumir API pública aberta**: o primeiro passo é **contato comercial** para confirmar existência de API/parceria, escopo (monitoramento de processos, diários, jurisprudência), preço, limites e **autorização contratual de uso e armazenamento**.
* **Não** fazer *scraping* do site (viola termos e é risco jurídico/técnico).
* Implementar `JusbrasilProvider` atrás da mesma interface **somente após contrato**; até lá, DataJud + DJEN + fontes públicas entregam o essencial.
* Plano B se não houver API: integração via *e-mail de alertas* (parsing de alertas que o próprio advogado já recebe do Jusbrasil, com consentimento) — frágil, só como ponte.

### 7.4 Conformidade
Consultas por nome de pessoa = tratamento de dado pessoal (base legal: exercício regular de direitos/execução de contrato; finalidade restrita ao mandato). Registrar na trilha **quem consultou o quê** e atualizar RoPA. Não armazenar mais do que o necessário; respeitar segredo de justiça.

---

## 8. IA que trabalha e aprende com o escritório (o diferencial) — CAD-180…189

### 8.1 Objetivo
O sistema **observa, sugere, executa o que é seguro e aprende com as correções** — e o advogado continua responsável pelas decisões relevantes (LGPD art. 20: direito a revisão de decisões automatizadas; OAB: responsabilidade profissional indelegável; resolução do CNJ sobre IA no Judiciário como referência de boas práticas **[VALIDAR texto vigente]**).

### 8.2 Escada de autonomia por **tipo de ação** (não só por escritório)
Hoje a política é global por escritório (`off/suggest/supervised/autonomous_limited`). Evoluir para **matriz ação × nível**:

| Classe | Exemplos | Padrão | Pode subir para |
|---|---|---|---|
| **R0 — leitura/organização** | classificar documento, extrair dados, resumir publicação, sugerir etiqueta | executa e mostra | — |
| **R1 — rascunho interno** | minuta de peça, rascunho de resposta ao cliente, tarefa/prazo provisório | cria **rascunho** | auto-criar rascunho sem pedir |
| **R2 — ação interna reversível** | criar tarefa confirmada, mover card, preencher campo de cadastro, agendar lembrete | pede aprovação | **auto com desfazer (24 h)** após critério de confiança |
| **R3 — efeito externo reversível** | mensagem a cliente (WhatsApp), criar andamento no ERP, evento no calendário de terceiros | **sempre aprovação** | auto só para modelos pré-aprovados e destinatários permitidos |
| **R4 — irreversível/alto impacto** | **protocolar peça, aceitar acordo, informar prazo fatal, excluir dados, honorários/pagamentos** | **sempre aprovação do advogado**, sem opção de automatizar | nunca |

Regras fixas: R4 não é configurável; qualquer ação sobre **prazo fatal** exige dupla confirmação; kill switch por escritório/global continua soberano; limites diários (`daily_ai_request_limit`, `max_actions_per_ai_workflow`) permanecem.

### 8.3 Fila de decisões do advogado ("Central de aprovações")
Uma caixa única no app com tudo que a IA preparou e depende de decisão: o que, **por quê** (fontes/trechos), **confiança**, impacto e botões **Aprovar / Editar e aprovar / Rejeitar (com motivo)**. Notificação priorizada (prazo próximo primeiro) e resumo diário/semanal. `aigov` já tem `executions/pending` e `review` — vira a base.

### 8.4 Como o sistema "aprende" — sem treinar modelo de terceiros
1. **Memória do escritório (RAG por escritório):** embeddings de peças modelo, contratos, e-mails relevantes, decisões passadas e playbooks → busca vetorial **filtrada por `organization_id`**. Infra: extensão **pgvector** no Postgres (trocar imagem para `pgvector/pgvector:pg15` ou instalar extensão; testar upgrade em staging) **[DECISÃO técnica]**. Índice por escritório; *crypto-shredding* (§2) apaga memória do escritório que sair.
2. **Sinais de feedback** (dados mais valiosos): cada aprovação, edição (diff), rejeição e desfazer vira evento `ai_feedback` (ação, contexto mascarado, resultado, tempo de resposta). Nunca guarda mais do que precisa.
3. **Preferências aprendidas:** de padrões repetidos o sistema **propõe regras** ("Notam-se 12 intimações do TJSP com prazo de 15 dias úteis → criar tarefa automaticamente?"). **A regra só vale depois que o advogado aprova** e fica visível/editável/desligável em "Regras do escritório" (transparência e auditoria).
4. **Estilo e linguagem:** few-shot dinâmico com as melhores peças aprovadas do escritório (retrieval), sem *fine-tuning* com dados de clientes. **[DECISÃO futura]** *fine-tuning* só com consentimento contratual explícito, modelo isolado por escritório.
5. **Avaliação contínua:** *golden set* por escritório e por tarefa (extração, classificação, prazo): taxa de aceitação sem edição, erro de prazo, tempo economizado. Painel no Centro de Segurança/IA. Regressões bloqueiam promoção de nível.
6. **Promoção de autonomia assistida:** quando uma ação R1/R2 atinge critério (ex.: ≥ 30 execuções, ≥ 95 % aprovadas sem edição, 0 erro de prazo em 60 dias) o sistema **sugere** subir o nível; **o advogado/sócio decide** e fica registrado (quem, quando, critério). Qualquer erro grave rebaixa automaticamente e notifica.
7. **Isolamento e privacidade:** zero vazamento entre escritórios (testes automatizados de isolamento no RAG); provedores de IA com **retenção zero / sem treino** contratualmente; mascaramento prévio; lista de provedores permitidos por escritório (já existe).

### 8.5 "O sistema se gere sozinho" — automações-âncora para o piloto
1. **Triagem de entrada:** e-mail/WhatsApp/upload → classifica (cliente, processo, assunto, urgência) → cria/associa processo, tarefa e rascunho de resposta.
2. **Gestão de prazos:** publicação → prazo provisório → confirmação → agenda + lembretes + escalonamento ao sócio se não confirmado em X h.
3. **Rotina de processo:** andamento novo → resumo em linguagem simples → sugestão de próxima ação → (se aprovado) mensagem ao cliente.
4. **Produção de peças:** gerar minuta a partir do modelo do escritório + dados do caso + jurisprudência citada → revisão do advogado → exportar.
5. **Relatório semanal** ao sócio: prazos em risco, carga por advogado, honorários pendentes, ações da IA e economia de tempo.

---

## 9. Centralizar o setor jurídico dentro do sistema (roadmap de módulos)

| Módulo | Estado | Observação |
|---|---|---|
| Processos e andamentos | a construir (base: §7) | entidade `Case` com partes, número CNJ, tribunal, fase, responsáveis |
| Prazos e agenda | parcial (`Task`) | + calendário, feriados forenses, escalonamento |
| Publicações/intimações | a construir (§7) | fila + prazos provisórios |
| Clientes (CRM jurídico) | parcial (`ClientDocument`) | cadastro de cliente/parte com dados cifrados (§2), histórico, consentimento |
| Documentos e modelos | parcial | + OCR/extração (§5), versionamento, assinatura eletrônica **[DECISÃO: ICP-Brasil/Gov.br/Clicksign/D4Sign]** |
| Peças com IA | a construir (§8) | modelos do escritório + RAG + citações |
| Atendimento (WhatsApp/e-mail) | parcial | caixa unificada com triagem por IA |
| Financeiro/honorários | a construir | contratos de honorários, parcelas, boletos/PIX **[DECISÃO]** — toca dinheiro: R4 |
| Timesheet/produtividade | a construir | métricas por advogado/cliente |
| Relatórios e BI | parcial (dashboard) | KPIs jurídicos |
| Portal do cliente | futuro | acompanhamento de processo com acesso restrito |

Ordem de valor/esforço: **Processos+Prazos+Publicações → Documentos/Extração → Agenda → Central de aprovações → Peças → ERP → Financeiro**.

---

## 10. Fases, ordem e responsáveis

| Fase | Janela (estimativa) | Entrega | Quem |
|---|---|---|---|
| **0 — Pronto para uso real** | 1–2 sem | CAD-119/121/115/105, CAD-150 (cadastro não perde dados), plano cadastrado, e-mail transacional (SPF/DKIM/DMARC), CAD-151 backups offsite + chave GPG nova, Required reviewers no `production` | Thales, Ryan, Jullio |
| **1 — Dados protegidos** | 2–3 sem | CAD-152…154: criptografia de PII (expand/backfill/contract), arquivos cifrados, check `pii_encrypted`, RoPA/RIPD | Thales (+Jullio chaves) |
| **2 — Documentos e agenda** | 3–4 sem | CAD-160…164 (OCR/extração/revisão), CAD-165…168 (Google Calendar), SSO ativo | Thales, Ryan, Allan |
| **3 — Pesquisa e monitoramento** | 3–4 sem | CAD-170…175 DataJud + DJEN + notícias + legislação; Jusbrasil conforme contrato | Thales, Ryan |
| **4 — IA que aprende** | 4–6 sem | CAD-180…188: matriz de autonomia, Central de aprovações, feedback, RAG por escritório (pgvector), regras aprendidas, métricas | Thales, Ryan, Allan |
| **5 — ERPs e centralização** | contínuo | CAD-190…193 framework de conectores + 1º ERP; módulos da §9 | todos |

Dependências críticas: e-mail (→ recuperação de senha, convites, alertas); chaves/KEK (→ criptografia); pgvector (→ memória); verificação do Google (→ Calendar em produção); contrato Jusbrasil (→ provider); DPAs com suboperadores (→ IA, OCR, e-mail, backup, Google).

---

## 11. Segurança e conformidade transversais

* **Novos suboperadores** (Google, Microsoft, provedor de e-mail, storage de backup, OCR/IA externos, Jusbrasil): cadastrar em `privacy.Subprocessor`, **assinar DPA**, marcar `contract_verified`, atualizar `legal/subprocessors/` e a política de privacidade (nova versão → reaceite dos termos via 428).
* **RIPD (`docs/RIPD_MODELO.md`)** a atualizar para: decisões automatizadas, perfilamento do escritório (memória/IA), consulta a dados de terceiros (partes de processos).
* **Novos checks** no Centro de Segurança: `pii_encrypted`, `offsite_backup`, `restore_drill_recent`, `ai_feedback_tracking`, `connector_secrets_encrypted`, `mfa` (hoje FAIL de propósito — **CAD-107/MFA** entra antes de abrir a produção a usuários externos para OWNER/ADMIN/staff).
* **Threat model** das novas superfícies: SSRF nos conectores (reusar `ssrf.py`), injeção de prompt em documentos/publicações (`wrap_untrusted`), vazamento entre escritórios no RAG, abuso de OAuth (escopo mínimo, revogação), *webhooks* (assinatura + replay).
* Testes: isolamento multi-tenant obrigatório em toda feature nova; CI mantém gitleaks/Trivy/testes.

---

## 12. Backlog novo (cards)

| Card | Título | Resp. | Fase |
|---|---|---|---|
| CAD-150 | Cadastro preserva rascunho ao recarregar (sessionStorage, TTL, sem senha/CPF) | Ryan | 0 |
| CAD-151 | Backups offsite (B2/S3 + Object Lock), chave GPG nova, restore drill, `media/` | Jullio | 0 |
| CAD-152 | Criptografia de PII: envelope (KEK/DEK por escritório), índice cego, `encrypt_pii` | Thales | 1 |
| CAD-153 | Arquivos de documentos cifrados (storage) + antivírus | Thales/Jullio | 1 |
| CAD-154 | Check `pii_encrypted`, rotação de chave testada, RoPA/RIPD atualizados | Thales/Jullio | 1 |
| CAD-155 | E-mail transacional (SPF/DKIM/DMARC) + alertas operacionais | Jullio/Thales | 0 |
| CAD-160 | Pipeline de documentos assíncrono (status, fila) | Thales | 2 |
| CAD-161 | OCR (ocrmypdf/Tesseract) em worker dedicado | Thales/Jullio | 2 |
| CAD-162 | Classificação + extração por tipo (schemas jurídicos) com confiança | Thales | 2 |
| CAD-163 | Tela de revisão de extração (visualizador + campos editáveis) | Ryan/Allan | 2 |
| CAD-164 | Prazos extraídos → tarefa provisória (regras de contagem/feriados) | Thales | 2 |
| CAD-165 | Google Calendar: OAuth por usuário, tokens cifrados, verificação do app | Thales/Jullio | 2 |
| CAD-166 | Sincronização Task ↔ evento (push + watch/syncToken + conflitos) | Thales | 2 |
| CAD-167 | Tela de conexão/estado do calendário | Ryan/Allan | 2 |
| CAD-168 | Lembretes de prazo (D-5/D-2/D-0) e escalonamento | Thales | 2 |
| CAD-170 | Hub de fontes jurídicas (interface Provider, cache, rate limit, auditoria) | Thales | 3 |
| CAD-171 | Provider DataJud (monitoramento por nº CNJ) | Thales | 3 |
| CAD-172 | Provider DJEN/Comunica (intimações por OAB) + fila de publicações | Thales | 3 |
| CAD-173 | Notícias e clipping (RSS autorizados) + legislação (LexML) | Thales | 3 |
| CAD-174 | Busca unificada (ctrl+K) + pesquisa jurisprudencial com citação | Thales/Ryan | 3 |
| CAD-175 | Jusbrasil: contato comercial → provider (somente com contrato) | Jullio/Thales | 3 |
| CAD-176 | Telas: Processos, Publicações, Notícias, Pesquisa | Ryan/Allan | 3 |
| CAD-180 | Matriz de autonomia ação × nível + classes de risco R0–R4 | Thales | 4 |
| CAD-181 | Central de aprovações (fila, justificativa, confiança, desfazer 24 h) | Thales/Ryan/Allan | 4 |
| CAD-182 | Eventos `ai_feedback` (aprovar/editar/rejeitar) e métricas | Thales | 4 |
| CAD-183 | pgvector + memória do escritório (RAG isolado por tenant) | Thales/Jullio | 4 |
| CAD-184 | Regras aprendidas propostas e aprovadas pelo advogado ("Regras do escritório") | Thales/Ryan | 4 |
| CAD-185 | Promoção/rebaixamento de autonomia com critérios e auditoria | Thales | 4 |
| CAD-186 | Geração de peças com modelos do escritório + citações | Thales/Ryan | 4 |
| CAD-187 | Triagem de entrada (e-mail/WhatsApp/upload) | Thales | 4 |
| CAD-188 | Golden sets + painel de qualidade da IA; testes de isolamento do RAG | Thales/Jullio | 4 |
| CAD-190 | Framework de conectores declarativos (auth, mapeamento, ações, dry-run) | Thales | 5 |
| CAD-191 | Tela "Parametrizar conexão" (testar, mapear campos, escopo) | Ryan/Allan | 5 |
| CAD-192 | Conector Astrea (1º ERP) | Thales | 5 |
| CAD-193 | Conectores seguintes conforme demanda (Advbox/Projuris/Legal One/CPJ…) | Thales | 5 |
| CAD-194 | Módulo Processos (`Case`) + clientes/partes cifrados | Thales/Ryan | 5 |
| CAD-195 | Financeiro/honorários **[DECISÃO]** | — | 5 |
| CAD-196 | Assinatura eletrônica **[DECISÃO]** | — | 5 |

---

## 13. Decisões (respondidas em 2026-10-04) e o que falta

| # | Decisão | Resposta | Consequência / status |
|---|---|---|---|
| 1 | Planos, preços, trial, inadimplência | "Baseados no custo de IA + sistema, com créditos avulsos; dono ajusta limite por membro" | **Feito**: `docs/ANALISE_PRECOS_PLANOS.md` + `scripts/pricing_model.py` + CAD-119. Faltam valores finais aprovados. |
| 2 | Provedor de e-mail | "Alternativas e cenários" | **Feito**: `deploy/EMAIL.md` §1. Recomendação: Brevo agora, SES depois. Falta escolher. |
| 3 | Destino do backup externo | **Supabase** | `setup-offsite.sh` com atalho Supabase (CAD-151). Sem Object Lock: proteção pela cifra GPG. |
| 4 | E-mail e busca por nome | "Não pode perder a busca; deixar o filtro aberto" | **Desenho** (CAD-152): e-mail em claro (login); CPF/telefone/OAB/endereço cifrados com índice cego; **nome com índice de tokens/trigramas (HMAC)** para busca parcial. Ver §2.3. |
| 5 | Verificação do app Google | **Sim, iniciar já** | Passo a passo em `deploy/README.md` §9 (escopos não sensíveis do SSO) e §6.2 (Calendar: escopo sensível → pedir verificação com vídeo e política). **Ação do Jullio** (console do Google). |
| 6 | Jusbrasil | "Somos nós; módulo extra; análise crítica" | **Feito**: `docs/MODULO_JUSBRASIL.md`. Recomendação: fontes gratuitas primeiro, BYOK depois, add-on por faixa. |
| 7 | ERP depois do Astrea | **Projuris** | CAD-193 passa a ser o conector Projuris (**validar** API/parceria com o fornecedor). |
| 8 | Provedores de IA / OCR | **3 IAs + motor local que aprende** | **Feito (desenho)**: `docs/MOTOR_IA_LOCAL.md`. OCR local (Tesseract) primeiro; pago só se a qualidade exigir. |
| 9 | pgvector (staging primeiro) | **Sim** | **Feito (sem teste em servidor)**: `deploy/scripts/upgrade-postgres-pgvector.sh` (CAD-159). Ver nota: o Postgres é compartilhado. |
| 10 | Escritório piloto | ainda decidindo | Bloqueia a validação das automações-âncora (§8.5). |

## 14. Riscos principais e mitigação

| Risco | Mitigação |
|---|---|
| IA errar prazo/precedente | R4 sempre humano; citação obrigatória; golden set; dupla confirmação de prazo fatal |
| Perda de chave de criptografia | KEK em cofre fora do servidor; teste de restauração; dupla custódia |
| Vazamento entre escritórios (RAG) | filtro obrigatório por tenant na camada de acesso + testes automatizados + índices por escritório |
| Dependência de APIs de terceiros | cache, *circuit breaker*, provedores plugáveis, degradação graciosa |
| Verificação do Google demorar | piloto em modo *Testing*; escopo mínimo; iniciar cedo |
| Escopo gigante | fases com entrega utilizável e smoke-test a cada uma; cortar módulos da §9 sem perder o núcleo |
| Custo de IA/OCR | limites por plano, cache de resultados, mascaramento e modelos menores para triagem |
