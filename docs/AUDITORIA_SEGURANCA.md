# Auditoria de Segurança — Cadrius (back-end)

Escopo: código em `main` (Django/DRF/JWT, allauth, Axes, Django-Q, Docker/Traefik, CI/CD).
Legenda: ✅ corrigido nesta branch · 🟡 mitigado em parte · ⛔ **ação manual necessária** · 📌 pendente (decisão/PR separado).

## 1. Crítico

| # | Achado | Estado |
|---|--------|--------|
| C1 | **Senha de app do Gmail em texto puro** em `.github/workflows/deploy.yml` (e no histórico do git) | ✅ removida do arquivo (agora via Secrets). ⛔ **Revogar/rotacionar essa senha no Google agora** — continua no histórico do git |
| C2 | **Produção assinava JWT com a `SECRET_KEY` pública padrão**: o deploy gera `DJANGO_SECRET_KEY`, mas o `settings.py` só lia `SECRET_KEY` → qualquer pessoa podia forjar tokens de qualquer utilizador | ✅ aceita os dois nomes e **recusa arrancar** em produção com a chave padrão. ⛔ Após o deploy, todas as sessões/tokens atuais deixam de valer (esperado) |
| C3 | **Evolution API (WhatsApp)** com chave mestra pública (`cadrius_mestre_secreto_123`) e porta 8082 publicada na internet; o deploy gerava `EVOLUTION_API_KEY` que o código não lia | ✅ chave vem do `.env` (ambos os nomes), recusa arrancar com a padrão, porta só em `127.0.0.1`. ⛔ Rotacionar a chave e confirmar que as instâncias existentes continuam acessíveis |
| C4 | **Sem isolamento entre escritórios** em `main`: `WorkflowViewSet.queryset = Workflow.objects.all()` (qualquer autenticado lê/edita/apaga automações de todos); `TenantMiddleware` vê o JWT como anónimo (tenant sempre `None`) | 📌 já existe pronto na branch `feature/CAD060-CAD063` (TenantAwareViewSet + testes de vazamento) mas **não está em `main`** → **fazer o merge é o item nº 1** |
| C5 | **Backups `.sql.gz` com dados reais no git** e copiados para a imagem Docker | ✅ `backups/` agora no `.dockerignore`. ⛔ Remover do git + `filter-repo` + rotacionar segredos (ver `docs/PLANO_AUDITORIA_LGPD.md`, F1) |
| C6 | **Credenciais de terceiros em texto puro** (`MailBox.password`, `AppConnection.credentials`); `SECURITY.md` afirmava criptografia que não existia (`core/utils.py` ausente; `seed` importava função inexistente) | ✅ `core/utils.py` (Fernet + rotação via `a,b`), campos cifrados + migração que cifra as linhas existentes. ⛔ Definir `PROD_ENCRYPTION_KEY` (gerar com Fernet) **antes** do deploy; **guardar a chave** (perdê-la = perder as credenciais) |
| C7 | **CSP inativa**: `django-csp` 4.x ignora os antigos `CSP_*` (requirements sem versão fixa) — nenhum cabeçalho CSP era enviado | ✅ `CONTENT_SECURITY_POLICY` (v4) + `CSP_*` (v3), com `frame-ancestors 'none'`, `object-src 'none'` |

## 2. Alto

| # | Achado | Estado |
|---|--------|--------|
| A1 | **SSRF**: `Action.endpoint_url` arbitrário → worker chamava Redis/DB/Evolution/metadados cloud; redirects seguidos | ✅ `integrations/ssrf.py` (http/https, bloqueia IPs privados/loopback/link-local, sem credenciais na URL) + `allow_redirects=False`. Limite conhecido: não cobre DNS-rebinding entre a validação e a conexão |
| A2 | **Injeção de JSON no template**: valor vindo de webhook público (`x","number":"…"`) sobrescrevia campos da ação (ex.: desviar mensagens WhatsApp) | ✅ valores escapados para string JSON |
| A3 | **Stripe**: webhook validava assinatura com segredo `''` se não configurado (forjável); checkout usava relação inexistente (sempre 500) e devolvia `str(e)`; qualquer membro iniciava checkout | ✅ 503 sem segredo, `get_active_membership`, só OWNER/ADMIN, erros genéricos |
| A4 | **Escalada de privilégio**: um ADMIN podia convidar membros com cargo OWNER | ✅ só OWNER concede OWNER |
| A5 | **IDOR em tarefas**: `responsavel` aceitava qualquer utilizador de qualquer escritório (e enumerava IDs) | ✅ restrito a si e membros ativos do mesmo escritório |
| A6 | **Senhas fracas aceitas** (validadores só valiam no admin) | ✅ cadastro e troca de senha passam por `validate_password` |
| A7 | **Sem rate limit** em login/cadastro/refresh; Axes por IP com Traefik à frente (todos com o IP do proxy → um atacante bloqueia todos) | ✅ throttles `auth_login 10/min`, `auth_register 5/hour`, `auth_refresh 30/min`; Axes por IP **ou** utilizador, lendo `X-Forwarded-For` (`AXES_PROXY_COUNT`) |
| A8 | **JWT não revogável** (`token_blacklist` ausente) | ✅ app instalada + `POST /api/v1/auth/logout/`. 📌 Considerar access token de 15 min |
| A9 | `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` fixos no código (ignoravam o `.env` do deploy), com túnel ngrok pessoal | ✅ lidos do ambiente (defaults só para dev) |
| A10 | Compose de produção = compose de dev: `--reload`, porta 8000 (bypass do Traefik), painel Traefik inseguro `:8090`, Postgres `postgres/postgres` hard-coded | ✅ portas administrativas em `127.0.0.1`, `UVICORN_ARGS`, `TRAEFIK_API_INSECURE`, senha do Postgres do `.env`. ⛔ Ver nota abaixo sobre a senha do Postgres |
| A11 | **Sentry** `send_default_pii=True` + 100% traces (LGPD / transferência internacional) | ✅ `send_default_pii=False`, corpo de requisição nunca, traces 10% |
| A12 | Sem cabeçalhos/cookies seguros em produção | ✅ cookies `Secure`, HSTS (30 dias), `X-Frame-Options`, nosniff. `SECURE_SSL_REDIRECT` opcional (só ligar se o proxy enviar `X-Forwarded-Proto`) |

## 3. Médio / baixo

| # | Achado | Estado |
|---|--------|--------|
| M1 | Cadastro com CPF vazio (`''`, campo `unique`) → 2.º utilizador sem CPF dá erro 500 | ✅ grava `NULL` |
| M2 | Webhooks públicos sem throttle (`webhooks/views.py`) e log com número de telefone completo (PII) | ✅ throttle + número mascarado |
| M3 | Imagem Docker corre como root; `requirements.txt` em UTF-16 e **sem versões fixas** (supply chain/CSP quebrou por isso) | 📌 usar `pip-compile` com hashes + `USER` não-root |
| M4 | `/admin/` público e sem MFA | 📌 MFA (TOTP) para staff / restringir por IP no Traefik |
| M5 | SSO por domínio (`allowed_domain`) vincula automaticamente como MEMBER; Microsoft pode devolver e-mail não verificado | 📌 exigir e-mail verificado do provedor antes do vínculo |
| M6 | `ACCOUNT_EMAIL_VERIFICATION='none'`; enumeração de e-mail no cadastro | 📌 verificação de e-mail + resposta genérica |
| M7 | CSP ainda com `'unsafe-inline'` (necessário aos templates atuais) | 📌 nonces |
| M8 | `ModelViewSet` de `workflows` com serializers desatualizados em relação ao modelo (`ActionSerializer` referencia campos inexistentes) | 📌 corrigido na `feature/CAD060-CAD063` (parcial) |
| M9 | CI: `bandit` só em severidade alta; sem scan de dependências/segredos | ✅ `pip-audit` (não bloqueante). 📌 `gitleaks`/secret scanning |

## 4. Ações manuais antes do próximo deploy (ordem)

1. **Revogar a senha de app do Gmail** exposta (C1) e criar os secrets `PROD_IMAP_*` (ou remover o IMAP global).
2. Criar secrets no GitHub: `PROD_ENCRYPTION_KEY` (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`), `PROD_SENTRY_DSN`, `PROD_STRIPE_SECRET_KEY`, `PROD_STRIPE_WEBHOOK_SECRET`; confirmar `PROD_DJANGO_SECRET_KEY` e `PROD_EVOLUTION_API_KEY` (valor forte e **novo**).
3. **Senha do Postgres:** o volume de produção já foi criado com a senha `postgres`; mudar `POSTGRES_PASSWORD` no `.env` não a altera. Executar uma vez: `ALTER USER postgres PASSWORD '<segredo>';` e só então fazer o deploy (e fazer o mesmo na Evolution API, que usa o mesmo banco).
4. Fazer o merge de `feature/CAD060-CAD063` (isolamento por escritório) — C4.
5. Remover `backups/` do git/histórico (C5) e avaliar notificação (LGPD art. 48).
6. Informar o front-end: novo endpoint `POST /api/v1/auth/logout/` (`{"refresh": "..."}`) e limites de taxa (HTTP 429) em login/cadastro.

## 5. Como verificar

`python manage.py test` — `cadrius/tests_security.py` cobre cifra em repouso, SSRF, injeção de template, CSP, senhas, logout/blacklist, escalada de cargo, IDOR de tarefas e Stripe.
