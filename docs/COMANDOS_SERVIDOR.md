# Comandos do servidor depois de CAD-219 a CAD-224

**Regra de ouro:** chaves e senhas só no `.env` do servidor. Nunca envie por chat, e-mail ou GitHub.

## 0. Situação dos ramos

**Back:**
- `main` está em CAD-175.
- A PR do CAD-222 (que inclui o CAD-221) está aberta.
- CAD-223 e CAD-224 estão em ramos próprios, empilhados em cima do CAD-222.

**Front:** CAD-219 a CAD-222 estão na PR do CAD-222; CAD-223 e CAD-224 estão em ramos.

**Ordem do merge:** CAD-222, depois CAD-223, depois CAD-224, nos dois repositórios. Os três primeiros passos abaixo
valem para qualquer caminho de deploy.

Abaixo, `ENV` é `staging` (app-teste) ou `prod`, e `dc` é um atalho para não repetir:

```bash
ENV=staging        # depois repita tudo com ENV=prod
cd /opt/cadrius/$ENV
dc() { sudo docker compose --project-name cadrius-$ENV "$@"; }
```

## 1. Atualizar o código (deploy)

**Caminho normal:** merge em `develop` (teste) ou em `main` (produção). O GitHub Actions roda o `deploy.sh`.

**Caminho manual:**

```bash
sudo /opt/cadrius/infra/deploy/scripts/deploy.sh $ENV
```

O `deploy.sh` já faz sozinho:
- puxa o back e o front;
- reconstrói as imagens, o que instala `anthropic` e `psutil` (CAD-221);
- faz backup antes;
- roda **todas as migrações** ao subir o `web`;
- roda `setup_security_schedules`, que agenda as rotinas novas;
- confere a saúde e faz **rollback** se falhar.

**Migrações novas desde CAD-175:**
- accounts 0014–0016
- aigov 0004–0005
- assistant 0001–0002
- audit 0003
- automations 0004–0005
- billing 0008
- carteira 0002
- contacts 0002
- emails 0003
- forense 0002
- gcal 0002
- integrations 0004–0005
- marketing 0002
- support 0002

Elas rodam sozinhas.

## 2. Variáveis novas no `.env` (o deploy NÃO mexe no `.env`)

```bash
sudo nano /opt/cadrius/$ENV/.env
```

Confira contra `deploy/app/env.backend.template` e acrescente o que faltar.

| Variável | Desde | Para quê |
|---|---|---|
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | CAD-221 | Claude: automações, assistente e estratégia |
| `MARITACA_API_KEY`, `MARITACA_MODEL` | CAD-221 | Sabiá: redação jurídica |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | — | Leitura de documentos |
| `GROQ_API_KEY`, `GROQ_MODEL` | CAD-221 | Triagem (tem plano grátis) |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_PAID` | CAD-221 | Marketing. `GEMINI_PAID=true` só com plano pago, para receber dado de cliente |
| `MISTRAL_API_KEY`, `MISTRAL_PAID`, `OPENROUTER_*`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | CAD-221 | Opcionais (reservas) |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | — | Cobrança. Em staging use **sk_test_** |
| `STRIPE_PAYMENT_METHODS` | CAD-224 | `card` (padrão) ou `card,boleto`, depois de ativar no Stripe |
| `FRONTEND_URL` | — | `https://app.cadrius.ia.br` (ou app-teste): retorno do checkout |
| `EMAIL_HOST`, `EMAIL_*`, `DEFAULT_FROM_EMAIL` | — | E-mails, inclusive a ação "Enviar e-mail" dos fluxos (CAD-224) |
| `FOCUSNFE_TOKEN`, `FOCUSNFE_BASE` | CAD-175 | NFS-e do Cadrius. Comece em homologação |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | — | Login Google |

`AI_PROVIDER_ORDER` e `AI_ASSISTANT_PROVIDER_ORDER` agora só definem a ordem das reservas. A ordem principal fica na
Gestão → IA por atividade.

**Depois de editar o `.env`, recrie o web e o worker** (sem isso eles não leem as variáveis novas):

```bash
dc up -d --force-recreate web worker
```

## 3. Comandos únicos (depois do deploy e do `.env`)

```bash
# 3.1 Rotinas agendadas. O deploy.sh já roda; repita se subiu sem ele. Inclui finance_daily, automations_tick e gcal_pull.
dc exec web python manage.py setup_security_schedules

# 3.2 Planos e pacotes. Primeiro só mostra o que faria; depois grava. Os preços precisam do OK da diretoria.
dc exec web python manage.py seed_plans
dc exec web python manage.py seed_plans --apply

# 3.3 IA: diagnóstico (provedores com chave, cadeia efetiva por atividade, quem liberou o quê)
dc exec web python manage.py cadrius_ia_provedores
#     liberar provedores para os escritórios que JÁ existem (os novos escolhem em Segurança → IA segura)
dc exec web python manage.py cadrius_ia_provedores --liberar ANTHROPIC,MARITACA,OPENAI,GROQ

# 3.4 Pagamentos: o que falta para cobrar (não mostra chaves). --online consulta o Stripe, somente leitura.
dc exec web python manage.py cadrius_pagamentos
dc exec web python manage.py cadrius_pagamentos --online

# 3.5 E-mail funcionando? (recuperação de senha, avisos, ação "Enviar e-mail")
dc exec web python manage.py send_test_email voce@cadrius.ia.br

# 3.6 Equipe Cadrius: áreas de cada pessoa. A área nova "juridico" (CAD-223) é para o calendário forense.
#     O nível "só consulta" é marcado na tela Gestão → Equipe Cadrius.
dc exec web python manage.py cadrius_staff pessoa@cadrius.ia.br --areas ti,financeiro,fiscal,juridico
```

**Só em staging (contas de validação; nunca em produção):**

```bash
dc exec web python manage.py seed_validation_users            # cria e imprime as senhas uma única vez
dc exec web python manage.py seed_validation_users --reset-passwords
```

## 4. Configurações fora do servidor

1. **Webhook do Stripe:**
   - painel do Stripe → Developers → Webhooks → endpoint `https://api.cadrius.ia.br/api/billing/webhook/` (em
     staging, `api-teste`);
   - eventos: `checkout.session.completed`, `invoice.paid`, `invoice.payment_succeeded`, `invoice.payment_failed`,
     `customer.subscription.deleted`;
   - copiar o "signing secret" para `STRIPE_WEBHOOK_SECRET`, depois `dc up -d --force-recreate web worker`.
2. **Google Agenda (CAD-222):** no Google Cloud, cadastre como URI de redirecionamento
   `https://api.cadrius.ia.br/api/v1/integrations/google-calendar/callback/`. A tela Integrações → Google Agenda mostra
   o endereço exato.
3. **Plugins / conector MCP (CAD-222):** o endereço que o escritório cola no Claude ou no ChatGPT aparece em
   **Plugins**. Não precisa de comando.
4. **Ordem da IA por atividade (CAD-224):** Gestão Cadrius → **IA por atividade**. Já vem na recomendação do estudo.

## 5. Conferência final (5 minutos)

```bash
sudo cadrius-status                                   # contêineres, saúde, backups e timers
dc logs --tail=50 web worker                          # sem erros na subida
dc exec web python manage.py showmigrations | grep '\[ \]' || echo "migrações OK"
```

Depois, no navegador:
1. A Gestão abre direto para a equipe Cadrius.
2. Gestão → **IA por atividade** mostra "Atende agora" com a IA esperada em cada atividade.
3. Gestão → Financeiro → **Promoções**: crie um cupom de teste.
4. Faça um cadastro com o cupom no app-teste.
5. No Perfil, "Assinar" com cartão de teste do Stripe `4242 4242 4242 4242` (só com `sk_test_`). O estado deve virar
   **Ativa**.
