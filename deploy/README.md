# Cadrius — Servidor (VPS Locaweb): produção + teste, PostgreSQL e backups

**Servidor:** `vps71752.publiccloud.com.br` · **IP:** `191.252.221.133` · **Domínio:** `cadrius.ia.br`

```
Internet ──80/443──▶ Traefik (HTTPS Let's Encrypt, HSTS, rate-limit)
                      ├─ app.cadrius.ia.br        → frontend PROD   ┐
                      ├─ api.cadrius.ia.br        → Django PROD     │ stack  cadrius-prod    (/opt/cadrius/prod)
                      ├─ app-teste.cadrius.ia.br  → frontend TESTE  ┐
                      ├─ api-teste.cadrius.ia.br  → Django TESTE    │ stack  cadrius-staging (/opt/cadrius/staging)
                      └─ logs.cadrius.ia.br       → Dozzle (BasicAuth)
PostgreSQL 15 (1 contêiner, rede interna, sem porta publicada)
   ├─ banco cadrius_prod     (papel cadrius_prod)     ← só a produção enxerga
   ├─ banco cadrius_staging  (papel cadrius_staging)  ← só o teste enxerga (dados SINTÉTICOS)
   └─ papel cadrius_backup   (somente leitura)        ← usado só pelo backup
```

Cada ambiente tem o próprio Redis, `.env`, chaves de criptografia e senhas. **Nunca copie dados de produção para o teste** (LGPD).

## 0. Antes de tudo (5 minutos, manual)

1. **DNS (Locaweb → Gerenciar DNS)** — todos os registros **A** devem apontar para `191.252.221.133`:

   | Nome | Tipo | Valor |
   |---|---|---|
   | `@` e `www` | A | 191.252.221.133 |
   | `app`, `api` | A | 191.252.221.133 |
   | `app-teste`, `api-teste` | A | 191.252.221.133 |
   | `logs` | A | 191.252.221.133 |

   ⚠️ **Hoje `api` e `app` apontam para `191.252.222.162` (IP diferente do VPS).** Corrija antes do deploy; o bootstrap confere o DNS e se recusa a pedir certificado se estiver errado (o Let's Encrypt bloqueia o domínio após várias falhas).
2. **Firewall do painel da Locaweb (grupo de segurança):** liberar TCP **22, 80 e 443**. (O servidor também usa UFW.)
3. **Na SUA máquina** gere a chave dos backups (a privada nunca vai ao servidor):
   ```bash
   ./deploy/backup/make-keypair.sh        # gera cadrius-backup-public.asc e cadrius-backup-PRIVADA.asc
   scp cadrius-backup-public.asc root@191.252.221.133:/root/
   ```
   Guarde a **PRIVADA + a senha** em 2 lugares fora do servidor (gerenciador de senhas + mídia offline). Sem ela os backups são irrecuperáveis.
4. **Chave SSH do GitHub Actions** (na sua máquina): `ssh-keygen -t ed25519 -f cadrius_actions -N ""` → a **pública** vai no `--deploy-pubkey`, a **privada** vira o secret `VPS_SSH_KEY`.
5. **Merge:** o kit (`deploy/`) e as correções do back precisam estar nas branches `main` (produção) e `develop` (teste) — faça o PR da `CAD-104`. Se a `develop` ainda não existir, crie-a a partir da `main`. No front, as branches usadas são `main` e `Develop`.

## 1. Bootstrap (uma vez; pode repetir sem medo — é idempotente)

```bash
ssh root@191.252.221.133
git clone https://github.com/Baianosppd/Cadrius.git /root/cadrius && cd /root/cadrius
git checkout CAD-104        # (até o PR ser aprovado)
sudo ./deploy/bootstrap.sh \
  --acme-email SEU_EMAIL@dominio.com \
  --front-repo https://github.com/<org>/<repo-do-front>.git \
  --gpg-pubkey /root/cadrius-backup-public.asc \
  --deploy-pubkey "$(cat cadrius_actions.pub)" \
  --acme-staging            # 1ª vez: certificado de homologação (não gasta limite). Depois remova e rode de novo.
```

O bootstrap: atualiza o SO, cria swap, instala Docker, UFW (22/80/443), fail2ban e atualizações automáticas; cria o usuário `deploy`;
gera **todas** as senhas/chaves aleatórias (`/opt/cadrius/{prod,staging}/.env`, `/etc/cadrius/credenciais.txt`); sobe Traefik + PostgreSQL + Dozzle;
cria os bancos e papéis; agenda os backups; e faz o primeiro deploy de teste e de produção.

Repositório privado? Se o `git clone` falhar, o script mostra como criar uma *deploy key* somente-leitura.
Quando tudo estiver funcionando: refaça sem `--acme-staging` (apague antes `docker volume rm cadrius_traefik_acme`, se o certificado de homologação já foi emitido) e **só então** use `--lock-ssh` (testando um 2º terminal antes de fechar o 1º).

## 2. Depois do bootstrap

```bash
sudo cat /etc/cadrius/credenciais.txt            # senha do Dozzle (logs.cadrius.ia.br)
sudo nano /opt/cadrius/prod/.env                 # OPENAI_API_KEY, STRIPE_*, SENTRY_DSN, GEMINI/GROQ... (idem staging/.env)
sudo /opt/cadrius/infra/deploy/scripts/deploy.sh prod      # aplica as mudanças
sudo /opt/cadrius/infra/deploy/scripts/create-admin.sh prod seu@email.com   # acessa /admin/ e /security-center/
sudo cadrius-status                              # painel: contêineres, saúde, disco, backups, timers
```

**Teste (staging):** `https://app-teste.cadrius.ia.br` — o deploy cria o *Escritório Demo (TESTE)* com 4 usuários (dono, admin, membro, leitor) e senhas aleatórias **impressas uma única vez** no log do deploy. Stripe em chave `sk_test_...`, nunca a de produção.

## 3. Deploy automático (GitHub Actions)

Secrets em **Settings → Secrets → Actions** (no repo do back e no do front): `VPS_HOST=191.252.221.133`, `VPS_USER=deploy`, `VPS_SSH_KEY` (privada), `VPS_KNOWN_HOSTS` (saída de `ssh-keyscan -t ed25519 191.252.221.133`).
Crie os *environments* `staging` e `production` (em `production` marque **Required reviewers** → aprovação manual).

* push em `develop` → `deploy-staging.yml` → `deploy.sh staging`; push em `main` → `deploy.yml` → `deploy.sh prod` (backup pré-deploy, healthcheck `/readyz/`, **rollback automático**).
* Os **segredos da aplicação ficam só no servidor** — o GitHub guarda apenas o acesso SSH.
* **Repositório do front (somente leitura para mim):** copie `deploy-staging.yml`/`deploy.yml` trocando o job de CI pelo `npm ci && npm run lint && npm run build`; o passo de deploy é o mesmo `ssh ... deploy.sh <env>` (o deploy do servidor já puxa back **e** front). O `Dockerfile` e o `nginx.conf.template` do front vêm de `deploy/frontend/` (copiados pelo `deploy.sh`) — não precisa alterar o repositório do front. A URL da API é injetada no *build* (`VITE_API_URL=https://api[-teste].cadrius.ia.br/api/v1/`); o front deve lê-la de `import.meta.env.VITE_API_URL` (CAD-106).

## 4. Backups automáticos

| O quê | Quando | Onde |
|---|---|---|
| `cadrius_prod` | a cada 6 h (00/06/12/18:15) + antes de cada deploy | `/srv/cadrius/backups/prod/` |
| `cadrius_staging` | diário 02:45 | `/srv/cadrius/backups/staging/` |
| segredos (`.env`, chaves) | 1×/dia, cifrados | `/srv/cadrius/backups/secrets/` |
| **teste de restauração** | domingo 04:30 (restaura num banco descartável e compara contagens + trigger da trilha de auditoria) | alerta se falhar |

* **Cifrados com GPG** (chave pública no servidor, privada com você); dump em texto claro só em RAM (`/dev/shm`).
* **Retenção:** 3 dias (todos) · 14 diários · 60 dias de semanais · 400 dias de mensais (`/etc/cadrius/backup.env`).
* **Cópia externa (obrigatória):** um backup só no VPS não protege contra perder o VPS. Guiado e com teste de escrita:
  ```bash
  # 1) no provedor — DECIDIDO: Supabase Storage (bucket PRIVADO + chaves S3 em Storage → S3 Connection). Alternativas: Backblaze B2 / Wasabi / S3 (com Object Lock)
  sudo /opt/cadrius/infra/deploy/backup/setup-offsite.sh          # pede endpoint, bucket e chaves (sem eco) e grava RCLONE_REMOTE
  sudo /opt/cadrius/infra/deploy/backup/backup.sh prod manual
  sudo /opt/cadrius/infra/deploy/backup/verify-offsite.sh prod    # confere: existe no destino, tamanho e hash iguais, recente
  cadrius-status
  ```
  * **Supabase:** crie um bucket **privado** `cadrius-backups` (Storage → New bucket), gere as *S3 access keys* (Storage → Settings → S3 Connection) e informe
    o *project ref* e a região no script. O Supabase **não tem Object Lock** nem chave só de escrita: a proteção é a **cifra GPG** (o provedor só vê arquivo cifrado)
    e a guarda da chave S3 (só em `/root/.config/rclone/rclone.conf`, `chmod 600`). Confira o **limite de tamanho de arquivo** do projeto (a mídia diária pode passar de 50 MB).
  * Com B2/Wasabi/S3: chave **sem** permissão de apagar + Object Lock = ransomware no servidor não consegue destruir as cópias. Nesse caso use
    `OFFSITE_PRUNE=false` em `/etc/cadrius/backup.env` e deixe a retenção às regras de ciclo de vida do bucket.
  * O `verify-offsite.sh` roda **todo dia às 07:20** (timer) e alerta se a cópia sumiu, divergiu ou ficou velha; o resultado vira o controle
    `offsite_verified` do Centro de Segurança (e `restore_drill` para o teste semanal de restauração).
  * **Mídia** (documentos dos clientes, volume `media`) também é copiada: `media/<ambiente>/media_*.tar.gz.gpg`, 1×/dia, cifrada com a mesma chave.
    Restaurar: `gpg -d media_prod_X.tar.gz.gpg | docker compose -p cadrius-prod exec -T web tar -xz -C /app/media`.
* **Alertas:** `ALERT_WEBHOOK_URL` (Discord/Slack) e `HC_PING_URL_PROD` (healthchecks.io avisa se o backup **não rodar**).
* O **Centro de Segurança** (`/security-center/` → Postura → controle A.8.13) lê o status do último backup de produção (PASSA só se < 26 h, cifrado e com cópia externa).

### Rotacionar a chave GPG (quando a privada vazou ou trimestralmente por política)
```bash
# Na SUA máquina (nunca no servidor): gere o novo par; guarde a privada em cofre, 2 cópias, 2 pessoas
bash deploy/backup/make-keypair.sh      # gera cadrius-backup-public.asc (vai ao servidor) e cadrius-backup-PRIVADA.asc (fica com você)
scp cadrius-backup-public.asc root@191.252.221.133:/root/
# No servidor: importe só a PÚBLICA e troque o destinatário
sudo gpg --import /root/cadrius-backup-public.asc && sudo gpg --list-keys --fingerprint
sudo sed -i 's/^BACKUP_GPG_RECIPIENT=.*/BACKUP_GPG_RECIPIENT=<FINGERPRINT_NOVO>/' /etc/cadrius/backup.env
sudo deploy/backup/backup.sh all manual && sudo deploy/backup/verify-offsite.sh
# Só depois de conferir que há backups com a chave nova (local e fora): apague os antigos cifrados com a chave exposta
# (local: /srv/cadrius/backups/*/{recent,daily,weekly,monthly}; fora: pelo painel do provedor) e REVOGUE a chave antiga.
```

### Restaurar (na sua máquina ou temporariamente no servidor)
```bash
# 1) baixe o arquivo (rclone copy offsite:cadrius-backups/prod/recent/ . ) e confira o sha256
# 2) restaura num banco NOVO (pede a senha da chave privada; recusa sobrescrever cadrius_prod)
sudo /opt/cadrius/infra/deploy/backup/restore.sh cadrius_prod_XXXX.dump.gpg cadrius_restaurado cadrius_prod
# 3) confira os dados; para promover à produção:
cd /opt/cadrius/prod && docker compose -p cadrius-prod stop web worker
docker exec cadrius_postgres psql -U postgres -c "ALTER DATABASE cadrius_prod RENAME TO cadrius_prod_old;" \
                                   -c "ALTER DATABASE cadrius_restaurado RENAME TO cadrius_prod;"
docker compose -p cadrius-prod up -d
```
**Simulado trimestral** (ISO A.8.13): restaure um backup real **com a chave privada**, valide o login e `manage.py verify_audit_chain`, e anexe a evidência ao controle.

## 5. Operação do dia a dia

| Tarefa | Comando |
|---|---|
| Status geral | `sudo cadrius-status` |
| Logs ao vivo | `https://logs.cadrius.ia.br` (usuário `admin`) ou `docker logs -f cadrius-prod-web-1` |
| Backup manual | `sudo /opt/cadrius/infra/deploy/backup/backup.sh prod manual` |
| Deploy manual | `sudo /opt/cadrius/infra/deploy/scripts/deploy.sh <prod\|staging>` |
| Rodar comando Django | `cd /opt/cadrius/prod && docker compose -p cadrius-prod exec web python manage.py <cmd>` |
| WhatsApp (Evolution) | `COMPOSE_PROFILES=whatsapp` no `.env` do ambiente (+ rota própria; fora do escopo do primeiro teste) |

## 6. O que NÃO foi validado e limitações conhecidas

* O kit foi escrito e testado **sem acesso ao VPS e sem daemon Docker**: os scripts de banco e backup/restauração foram executados de ponta a ponta contra PostgreSQL 16 real (incluindo papel de menor privilégio, GPG, retenção, arquivo corrompido e restauração); os `docker-compose` foram validados com `docker compose config`. A primeira execução real é o bootstrap — se algo falhar, rode de novo (é idempotente) e envie o trecho do erro.
* **Login Google/Microsoft não funciona** em teste: as rotas `/api/v1/auth/google|microsoft/` que o front chama não existem no back (CAD-105). E-mail/senha funciona.
* `docker-socket-proxy` e MFA ainda pendentes (CAD-083/085/107).
* Segredos do histórico do git antigo precisam ser rotacionados (CAD-100).

## 7. Atualizar o servidor com o que está no git

```bash
sudo -i
/opt/cadrius/infra/deploy/scripts/update-kit.sh main          # scripts, compose, timers de backup (branch do KIT)
/opt/cadrius/infra/deploy/scripts/deploy.sh staging           # código: back em develop, front em Develop
/opt/cadrius/infra/deploy/scripts/deploy.sh prod              # código: back e front em main
# antes de mergear, dá para testar uma branch:  BACK_BRANCH=CAD-110 FRONT_BRANCH=CAD-113 .../deploy.sh staging
```
O deploy também corrige sozinho o `ALLOWED_HOSTS` de `.env` antigos (o healthcheck chama `127.0.0.1`).

**O kit se atualiza sozinho (CAD-170):** todo `deploy.sh` começa trazendo o kit da branch `main` (`update-kit.sh`) e, se ele mudou,
reinicia com a versão nova — o deploy pelo GitHub Actions nunca mais roda scripts velhos (foi o que impediu a `BLIND_INDEX_KEY` de ser
criada). Opções: `KIT_BRANCH=<branch>` (testar um kit de outra branch) e `KIT_AUTO_UPDATE=0` (desligar). Se a atualização falhar,
o deploy segue com o kit atual e avisa (detalhes em `/tmp/cadrius-kit-update.log`). **Uma única vez** depois deste merge, rode o
`update-kit.sh main` à mão para o servidor receber esta própria melhoria.

## 8. Certificados e teste de fumaça

```bash
sudo /opt/cadrius/infra/deploy/scripts/switch-acme.sh real       # troca homologação → Let's Encrypt de verdade (só o Traefik é recriado)
sudo /opt/cadrius/infra/deploy/scripts/switch-acme.sh staging    # volta para homologação (testes sem gastar limites)

# DNS, TLS, saúde, cabeçalhos, rotas públicas/protegidas, CORS, permissões e backups — não altera nada
/opt/cadrius/infra/deploy/scripts/smoke-test.sh staging --insecure     # --insecure enquanto o certificado for de homologação
SMOKE_USER=owner@teste.cadrius.ia.br SMOKE_PASS='...' /opt/cadrius/infra/deploy/scripts/smoke-test.sh staging
SMOKE_USER=voce@email.com SMOKE_PASS='...' /opt/cadrius/infra/deploy/scripts/smoke-test.sh prod
```
Ordem recomendada: `switch-acme.sh real` **antes** do primeiro deploy de produção (assim `app.`/`api.` já nascem com certificado de verdade).

## 9. Ativar o login social (Google e Microsoft) — CAD-105

O back conduz o fluxo (`/api/v1/auth/google/` → provedor → `/api/v1/auth/google/callback/` → front). O SSO **só entra em contas
que já existem** (e-mail verificado pelo provedor) ou cria **membro** quando o domínio do e-mail é de um escritório cadastrado
(`allowed_domain`). Quem não tem conta precisa se cadastrar antes; o aceite dos termos continua obrigatório.

**Google** — console.cloud.google.com → projeto "Cadrius":
1. *APIs e serviços → Tela de permissão OAuth*: tipo **Externo**, nome, logo, domínio `cadrius.ia.br`, links da política de privacidade e dos termos.
   Escopos: apenas `openid`, `email`, `profile` (não sensíveis: dispensam a verificação demorada do Google).
2. *Credenciais → Criar credenciais → ID do cliente OAuth → Aplicativo da Web*, **um por ambiente**:
   - URI de redirecionamento autorizado: `https://api.cadrius.ia.br/api/v1/auth/google/callback/` (teste: `https://api-teste.cadrius.ia.br/...`).
   - Origens JavaScript: não são necessárias (o fluxo é no servidor).
3. Copie o *Client ID* e o *Client secret*.

**Microsoft** — portal.azure.com → *Microsoft Entra ID → Registros de aplicativo → Novo*:
1. Contas compatíveis: "Contas em qualquer diretório organizacional e contas pessoais da Microsoft".
2. URI de redirecionamento (Web): `https://api.cadrius.ia.br/api/v1/auth/microsoft/callback/`.
3. *Certificados e segredos → Novo segredo do cliente* (anote a validade — **renove antes de vencer**; máx. 24 meses).
4. *Configuração de token → Adicionar declaração opcional → ID token → `xms_edov`* (e-mail com domínio verificado). **Sem ela o back não vincula por e-mail**
   (a Microsoft não garante que o e-mail do token seja verificado).

**No servidor** (`/opt/cadrius/<prod|staging>/backend.env` — nunca no git):
```
GOOGLE_CLIENT_ID=...        GOOGLE_CLIENT_SECRET=...
MICROSOFT_CLIENT_ID=...     MICROSOFT_CLIENT_SECRET=...     MICROSOFT_TENANT=common
API_PUBLIC_URL=https://api.cadrius.ia.br
FRONT_SSO_ENABLED=true      # mostra os botões no front (rebuild do front)
```
Depois: `deploy.sh <ambiente>` (reinicia o back e refaz o build do front com `VITE_SSO_ENABLED=true`).

**Testar:** abra `https://app-teste.cadrius.ia.br` → "Continuar com Google". Erros voltam ao login com um código
(`no_account`, `email_unverified`, `state_invalid`, `token_invalid`, …); os motivos ficam na trilha de auditoria (`auth.sso.login`, outcome `denied`).

## 11. Dados pessoais cifrados em repouso — o que muda e como operar (CAD-152)

**O que é cifrado (Fernet, no banco):** CPF, telefone, nº da OAB, nome e sobrenome do usuário; CNPJ, endereço, telefones e e-mail corporativo do escritório;
**nome do cliente** nos documentos; credenciais de integrações e senhas de e-mail (já eram). **Fica em claro (decisão):** e-mail/login, razão social/nome do escritório, UF.

**Busca continua funcionando:** CPF/CNPJ por **índice cego** (exato e único, em qualquer formato); **nome por índice de tokens** (parcial e sem acento:
`?cliente=silv` em `/api/v1/documentos/`, `?q=` em `/api/v1/funcionarios/`, busca do admin). No banco só há hashes. Ver `core/pii.py`.

**Chaves (guarde as duas; entram no backup diário de segredos). Passo a passo do cofre: `docs/CHAVES_CRIPTOGRAFIA.md`.**
| Chave | Para quê | Se perder |
|---|---|---|
| `ENCRYPTION_KEY` | decifrar os dados | **os dados cifrados ficam irrecuperáveis** — mantenha cópia em cofre fora do servidor |
| `BLIND_INDEX_KEY` | buscar por CPF/CNPJ/nome | nada se perde: gere outra e rode `manage.py encrypt_pii` para reindexar |

O `deploy.sh` gera a `BLIND_INDEX_KEY` sozinho em ambientes antigos que não a têm.

**Publicar (1ª vez):** o deploy roda as migrações (trocam o tipo das colunas e cifram/indexam o que já existe). Depois:
```bash
cd /opt/cadrius/<env> && docker compose --project-name cadrius-<env> exec web python manage.py encrypt_pii --dry-run   # deve mostrar 0 linhas em texto puro
```
O Centro de Segurança passa a mostrar o controle **pii_encrypted** (conta linhas em texto puro direto no banco).

**Rotacionar a `ENCRYPTION_KEY`:** 1) gere uma chave nova; 2) `ENCRYPTION_KEY="NOVA,ANTIGA"` no `.env` e redeploy; 3) `manage.py encrypt_pii` (recifra tudo com a nova);
4) confira `encrypt_pii --dry-run` e os testes de login; 5) remova a antiga do `.env`. **Teste isto em staging antes da produção.**

**Atenção:** `QuerySet.update(...)` e SQL direto **não** atualizam os índices — depois de qualquer carga em massa rode `encrypt_pii`.
Ordenar por nome no banco não funciona (valor cifrado): a API ordena em Python. Se algum relatório precisar filtrar/ordenar por esses campos, peça uma consulta própria.

## 12. Google Calendar — cada escritório com o PRÓPRIO app do Google (CAD-162)

Decisão: **cada cliente usa o seu app OAuth no Google Cloud**. Assim o Cadrius **não** precisa passar pela verificação do Google para o escopo de agenda
(`calendar.events` é "sensível"): quem cria e limita o app é o próprio escritório. Sem chave do Google no servidor do Cadrius — o escritório cadastra
as credenciais na tela **Integrações → Google Calendar** (o segredo é cifrado no banco e nunca volta pela API).

**Passo a passo para o escritório (quem tem Google Workspace faz em ~10 min):**
1. https://console.cloud.google.com → criar um projeto (ex.: "Cadrius – Agenda").
2. *APIs e serviços → Biblioteca* → ativar a **Google Calendar API**.
3. *Tela de permissão OAuth*:
   * **Workspace:** tipo **Interno** (só usuários do domínio; **não exige verificação do Google**). Ideal.
   * **Gmail comum:** tipo **Externo** em modo **Teste** e adicionar os e-mails dos usuários em "Usuários de teste" (limite de 100; o login expira a cada 7 dias em modo de teste — o Cadrius pede para reconectar).
   * Escopo: apenas `.../auth/calendar.events`.
4. *Credenciais → Criar credenciais → ID do cliente OAuth → Aplicativo da Web*:
   * **URI de redirecionamento autorizado:** o valor mostrado na tela do Cadrius (ex.: `https://api.cadrius.ia.br/api/v1/integrations/google-calendar/callback/`).
5. Na tela do Cadrius (dono/administrador): colar o **ID do cliente** e o **segredo** → salvar. Depois cada usuário clica em **Conectar** e autoriza.

**Como funciona:** tarefa com "sincronizar" vira evento (cor pela prioridade; concluída vira "✔" e livre). Editar/excluir no Cadrius atualiza/remove o evento.
Mudar horário ou título no Google atualiza a tarefa (a cada 15 min; botão "Sincronizar agora"). Apagar o evento no Google **desliga** a sincronização, mas a tarefa permanece.
**Privacidade:** desmarque "enviar título e descrição" e o evento sai só como "Tarefa Cadrius".
**Falhas:** token revogado → a conexão fica "Precisa reconectar" e o usuário recebe uma notificação. Limites do Google (429) são reenfileirados.
**Agenda (django-q):** `gcal_pull` a cada 15 min, criado pelo `setup_security_schedules` (o `deploy.sh` já roda).

## 13. Leitura automática de documentos e arquivos cifrados (CAD-163/164)

**O que acontece no upload:** o documento é salvo **cifrado no disco** (Fernet, mesma `ENCRYPTION_KEY`; o download decifra) e entra numa fila:
confere o **tipo pelo conteúdo** (um `.exe` renomeado para `.pdf` é recusado) → antivírus (se configurado) → texto (PDF, DOCX, TXT; imagem/PDF digitalizado só com OCR)
→ **mascara CPF/CNPJ/e-mail/telefone** → IA (provedor mais barato permitido: Groq → Gemini → OpenAI; respeita política, kill switch e créditos) →
**"Aguardando revisão"**. Só quando uma pessoa **confirma** os prazos viram tarefas (e vão ao Google Calendar se a pessoa tiver conectado).
Cobra **1 crédito por extração bem-sucedida** (peso editável em Financeiro → Pesos de crédito). Falha de IA não cobra.

**Depois do deploy (uma vez):** cifrar os arquivos antigos —
`docker compose --project-name cadrius-<env> exec web python manage.py encrypt_files --dry-run` e, se estiver certo, sem `--dry-run`.
Limite por arquivo: `DOCUMENT_MAX_BYTES` (25 MB; a cifra é em memória). Os backups da pasta `media/` já vão cifrados duas vezes (arquivo + GPG).

**OCR (opcional, desligado por padrão):** `WITH_OCR=1` no `.env` do ambiente e `deploy.sh` (instala Tesseract `por`+`eng` e poppler; a imagem cresce e ganha pacotes que o Trivy
passa a examinar — rode o CI antes). Sem OCR, escaneados ficam "não processados" com o motivo, e dá para reprocessar depois que o OCR for ligado. Para melhor qualidade em manuscrito,
avalie OCR pago (ele passa a ser suboperador: DPA).

**Antivírus (opcional):** suba um contêiner `clamav/clamav` (≥ 1,5 GB de RAM) na rede interna e defina `CLAMAV_HOST=<nome>`. Configurado e **fora do ar = falha fechada**
(o documento não é processado até o antivírus voltar); infectado = bloqueado e auditado (`document.blocked`).

**Auditoria:** `document.extracted` (provedor, páginas/caracteres, OCR) e `document.extraction_confirmed` — sem o conteúdo.

## 14. Motor Cadrius: a IA que aprende com o escritório (CAD-165)

O diferencial do produto, **sem treinar modelo de terceiros**: o sistema **lembra, mede e propõe — o advogado decide**.

| Peça | O que faz | Onde |
|---|---|---|
| **Leitura local** | Número do processo, tipo e prazos explícitos por regras, sem IA e sem custo. Primeira passada e **plano B** (sem crédito, política, provedor ou pausa de cobrança): o advogado sempre recebe um rascunho | `brain/local.py` |
| **Memória do escritório** | Peças-modelo, anotações e leituras **aprovadas**, com busca por similaridade (embeddings locais, sem rede), **isolada por escritório** e cifrada | `brain/memory.py` |
| **Few-shot** | Antes de chamar a IA, junta 2 exemplos aprovados parecidos (mascarados, tratados como texto não confiável) | `documents/pipeline.py` |
| **Feedback** | Cada confirmação registra se a pessoa aprovou sem editar, editou ou rejeitou e **o que mudou** | `brain/feedback.py` |
| **Regras do escritório** | Correção repetida (ex.: OUTRO→DECISAO ≥ 5 vezes) vira **proposta**; só vale depois de aprovada por dono/administrador; visível e desligável | `OfficeRule` |
| **Matriz de autonomia** | Por tipo de ação: `off`/`review`/`auto`/`auto_undo`. **R4 (protocolar, prazo fatal, pagamento, exclusão) nunca é automático**; R3 fica em revisão | `brain/autonomy.py` |
| **Promoção sugerida** | Se ≥ 30 decisões em 60 dias, ≥ 95 % aprovadas sem edição e nenhuma rejeitada/desfeita → **sugere** subir o nível; **só o dono** aprova | `AutonomyProposal` |
| **Rede de segurança** | Confirmação automática é desfeita em até 24 h (apaga as tarefas, volta para revisão) e **rebaixa a autonomia na hora** | `…/extraction/undo-auto/` |

**Agenda:** `brain_evaluate` roda diariamente (criado pelo `setup_security_schedules`): propõe regras e sugere promoções. Nada muda sozinho.
**APIs** (`/api/v1/brain/`): `approvals/` (Central de aprovações), `rules/`, `autonomy/`, `memory/` e `memory/search/`.
**Limites conhecidos:** os embeddings são lexicais (acham vocabulário parecido, não sinônimos) — para semântica troque por um modelo local via `BRAIN_EMBEDDER` ou use pgvector (`§10`);
o aprendizado é por escritório (não há conhecimento compartilhado entre clientes, de propósito). LLM local de uso geral fica para quando houver máquina com GPU (`docs/MOTOR_IA_LOCAL.md`).
