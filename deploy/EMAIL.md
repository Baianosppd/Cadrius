# E-mail transacional do Cadrius (CAD-155)

Usado por: recuperação de senha (CAD-115), convites de equipe, avisos de prazo e alertas. **Sem `EMAIL_HOST` configurado o back não envia nada**
(em produção o backend é `dummy`, para que links de recuperação nunca caiam nos logs).

## 1. Escolha o provedor [DECISÃO] — alternativas e cenários

Preços e franquias mudam: confirme nos sites. Faixas abaixo são **ordem de grandeza** para dimensionar a decisão.

| Provedor | Melhor cenário | Pontos fortes | Pontos de atenção |
|---|---|---|---|
| **Amazon SES** (`sa-east-1`) | volume médio/alto, custo mínimo, já usa AWS | o mais barato por e-mail (centavos de dólar por mil); DKIM por CNAME; região em São Paulo | começa em *sandbox* (pedido para sair); painel/relatórios básicos; reputação é sua responsabilidade; precisa de SNS p/ bounces |
| **Brevo** (ex-Sendinblue) | começar rápido, equipe pequena, quer painel e templates | plano gratuito com limite diário; SMTP simples; painel de entregabilidade | limites diários no gratuito; suporte variável |
| **Mailgun / SendGrid** | equipe técnica, precisa de API, webhooks de evento, logs | boa API e *webhooks* de bounce/spam; validação de e-mail | mais caro que SES; planos gratuitos limitados/mudando |
| **Postmark** | só e-mail **transacional** crítico (recuperação de senha, alertas) | melhor entregabilidade/velocidade; separa transacional de marketing | mais caro por volume; sem foco em marketing |
| **SMTP da Locaweb** (já contratado) | zero custo extra e pouco volume | nada novo a contratar | reputação de IP compartilhado; limites por hora/dia; menos visibilidade de bounces |
| **Google Workspace / Microsoft 365 SMTP** | só alertas internos e volume mínimo | já existe | limites baixos e política de uso: **não** serve para e-mail aos clientes em volume |

**Como escolher:**
* **Até ~3 mil e-mails/mês e quer simplicidade → Brevo** (ou o SMTP da Locaweb se já está pago).
* **Crescimento e custo → Amazon SES** (melhor custo; exige um pouco mais de configuração).
* **E-mail que não pode cair em spam (recuperação de senha de advogado) → Postmark** ou SES com domínio bem aquecido e DMARC.
* **Recomendação para o Cadrius agora:** **Brevo** para começar (rápido, gratuito no início) e **migrar para SES** quando passar do plano gratuito — a troca é só mudar `EMAIL_HOST/USER/PASSWORD` no `.env`, o código não muda.

Registre o provedor como **suboperador** (`privacy.Subprocessor`) e assine o DPA: ele recebe e-mail e nome dos usuários.

## 2. DNS do domínio `cadrius.ia.br` (obrigatório para não cair em spam)
Os valores exatos vêm do painel do provedor; o formato é este:
| Tipo | Nome | Valor (exemplo) |
|---|---|---|
| TXT (SPF) | `@` | `v=spf1 include:<spf-do-provedor> -all` (um único SPF por domínio) |
| CNAME/TXT (DKIM) | `<seletor>._domainkey` | fornecido pelo provedor (1 a 3 registros) |
| TXT (DMARC) | `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@cadrius.ia.br; adkim=s; aspf=s` — suba para `quarantine` e depois `reject` após 2–4 semanas sem falhas |

Remetente: `Cadrius <no-reply@cadrius.ia.br>` (`DEFAULT_FROM_EMAIL`). Confira em https://www.mail-tester.com (nota ≥ 9/10).

## 3. Configure no servidor
Em `/opt/cadrius/prod/backend.env` e `/opt/cadrius/staging/backend.env` (nunca no git):
```
EMAIL_HOST=smtp.provedor.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Cadrius <no-reply@cadrius.ia.br>
```
Depois `deploy.sh <ambiente>` e teste:
```bash
cd /opt/cadrius/prod && docker compose --project-name cadrius-prod exec web python manage.py send_test_email voce@seudominio.com
```
Teste ponta a ponta: em `https://app.cadrius.ia.br/esqueceu-a-senha` peça a redefinição para um usuário real e confira a caixa (e o spam).

## 4. Staging
Use um provedor/caixa de captura (ex.: Mailpit, Mailtrap) ou o mesmo SMTP com um **remetente de teste** e só destinatários seus — nunca envie e-mail de teste para clientes.

## 5. Monitoramento
* Falhas de envio ficam na trilha (`auth.password.reset_requested`, outcome `error`) e no Sentry.
* Acompanhe bounces/spam no painel do provedor; taxa de reclamação > 0,1 % exige ação imediata.
