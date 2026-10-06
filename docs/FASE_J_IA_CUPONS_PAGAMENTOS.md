# Fase J (CAD-224): IA por atividade, cupons, prontidão de pagamentos e varredura de módulos

Estudo completo da IA por atividade: [`ESTUDO_IA_POR_ATIVIDADE.md`](ESTUDO_IA_POR_ATIVIDADE.md).
Comandos do servidor de CAD-219 a CAD-224: [`COMANDOS_SERVIDOR.md`](COMANDOS_SERVIDOR.md).

## 1. Cada IA na atividade em que mais rende
- **Onde configurar:** Gestão Cadrius → **IA por atividade** (área TI).
- **Seis atividades:**
  - automações e assistente (**Claude** primeiro);
  - estratégia de caso (**Claude**);
  - redação jurídica (**Sabiá/Maritaca**);
  - leitura de documentos (**OpenAI**);
  - triagem (**Groq**);
  - marketing (**Gemini**).
- **Editar a cadeia:** cada cadeia é editável. Dá para subir, descer, tirar ou incluir uma IA, e marcar "usar as demais
  como reserva". O botão "Usar a recomendada" desfaz as mudanças. Toda troca é auditada (`ai.route_changed`).
- **Quando uma IA cai:** a próxima da cadeia assume na mesma requisição. Depois de 3 falhas seguidas, a IA vai para o
  fim da fila por 5 minutos e volta sozinha.
- **Onde vale:**
  - assistente (com ferramentas e no modo estratégia);
  - leitura de documentos (com a leitura local como último recurso);
  - minutas e ferramentas de texto;
  - triagem de publicações e de e-mails;
  - marketing;
  - fluxos criados pela IA.
- **O que não muda:**
  - IA que treina com os dados nunca recebe dado de cliente;
  - o escritório continua escolhendo quais IAs aceita;
  - a chave própria (BYOK) vem primeiro para quem tem.
- **No terminal:** `python manage.py cadrius_ia_provedores` mostra a cadeia efetiva de cada atividade.

## 2. Cupons liberados pela Gestão
- **Onde criar:** Gestão Cadrius → Financeiro → **Promoções**. São três tipos:
  - **Percentual** e **Valor fixo**: desconto na assinatura, que vale na 1ª cobrança, por N meses ou sempre;
  - **Dias extras de teste** (novo): de 1 a 90 dias, entram na hora.
- **Na abertura da conta:** o cadastro (pessoa física e empresa) tem o campo **"Cupom (opcional)"** na escolha do plano.
  - **Cupom inválido:** o cadastro avisa no próprio campo.
  - **Dias extras:** aplicados na hora.
  - **Desconto:** fica **reservado** e entra sozinho no primeiro pagamento. O Perfil mostra "Cupom X reservado no
    cadastro".
- **Durante o teste, no Perfil:** o dono ou admin pode digitar um cupom de dias extras e clicar em "Aplicar cupom".
- **Regras:** valem período, planos, limite de usos e uma vez por escritório. Cada uso é auditado
  (`billing.coupon_applied`). Cupom já usado não pode ter o desconto alterado: crie outro.

## 3. Prontidão para cobrar (validação)
| Item | Situação | O que fazer |
|---|---|---|
| Checkout de assinatura e créditos (Stripe) | Pronto no código: valida plano e cupom no servidor; o webhook só confia nos metadados gravados por nós | Preencher `STRIPE_SECRET_KEY` |
| Sem chave do Stripe | **Corrigido:** antes dava erro 500 genérico; agora a tela mostra "Pagamento on-line ainda não está disponível" (503) | — |
| Webhook (`/api/billing/webhook/`) | Recusa tudo enquanto `STRIPE_WEBHOOK_SECRET` estiver vazio, por segurança | Criar o endpoint no painel do Stripe com os 5 eventos abaixo e copiar o segredo para o `.env` |
| Passagem de "em teste" para "ativa" | Feita pelo webhook `checkout.session.completed`; renovação por `invoice.paid`; falha por `invoice.payment_failed`; cancelamento por `customer.subscription.deleted` | — |
| Volta do checkout | **Corrigido:** agora aparece o aviso "Pagamento enviado / cancelado" | — |
| Meios de pagamento | Só cartão por padrão | Boleto em assinatura: ativar no painel do Stripe e usar `STRIPE_PAYMENT_METHODS=card,boleto`. Pix: conferir no painel se a conta aceita Pix em assinatura |
| Planos e preços | Catálogo proposto em `seed_plans` (Start R$ 99, Pro R$ 299, Business R$ 799) | Diretoria aprova; `seed_plans --apply` |
| Nota fiscal do Cadrius | Focus NFe (`FOCUSNFE_TOKEN`), começa em homologação | Trocar `FOCUSNFE_BASE` para produção só depois de validar |

- **Diagnóstico:** `python manage.py cadrius_pagamentos` mostra o que falta, sem exibir chaves.
  - Com `--online`, também consulta a conta e os webhooks no Stripe, somente leitura.
  - Ele diz se a chave é de **teste** (não cobra) ou de **produção**.
- **Recomendação:** validar tudo com chave `sk_test_` e cartão de teste do Stripe. Só depois trocar para `sk_live_`.
  **A troca para cobrança real fica com você.**

Eventos do webhook: `checkout.session.completed`, `invoice.paid`, `invoice.payment_succeeded`, `invoice.payment_failed`,
`customer.subscription.deleted`.

## 4. Varredura dos módulos
- **Como foi feita:** varredura automática de **todas as telas**, entrando como:
  - dono;
  - advogado;
  - somente leitura;
  - equipe Cadrius com todas as áreas.

  Cada aba de cada tela foi aberta, registrando respostas 404/5xx da API, erros de JavaScript e textos como
  "em construção" ou "em breve".
- **O que foi encontrado e corrigido:**
  1. **Fluxos: "Enviar e-mail" não funcionava.** A ação existia no modelo, no gerador de fluxos por IA e na tela, mas
     o executor respondia "não implementado".
     - Agora envia pela conta de e-mail do escritório (ou pelo remetente do Cadrius).
     - Só envia para **alguém da equipe** ou para **contato que autorizou e-mail** (LGPD); o resto é recusado com o
       motivo.
     - O bloco foi liberado no editor visual.
  2. **Blocos "Em breve" no editor visual:** Projuris, SMS, Google Drive, Slack, Condição, Aguardar e Agendamento
     apareciam e não funcionavam. Saíram da biblioteca, com a orientação de usar **Automações → Regras** (25
     gatilhos, condições, horários e prazos) ou o bloco "Chamar webhook" (Slack e Teams aceitam webhook).
  3. **Login da equipe Cadrius:** abria o painel do escritório, que dava 403 em tudo, antes de ir para a Gestão. Agora
     vai direto para a Gestão.
  4. **Retorno do pagamento:** não havia aviso. Agora há (veja a seção 3).
- **Sem erros:** nenhuma outra tela teve erro de API ou de página.
  - Os 428 do primeiro acesso são o aceite de termos, que é esperado.
  - O 403 da equipe antes de ativar a verificação em duas etapas também é esperado.

### Plano do que fica para depois
| Item | Por quê | Proposta |
|---|---|---|
| Condições e espera no editor visual de fluxos | O motor de fluxos é linear (gatilho → ações) | As Regras já cobrem; unificar o editor visual com o motor de regras numa fase própria |
| SMS e WhatsApp oficial | Precisam do contrato com a Zenvia | O app já está no catálogo; ação de envio depois do contrato |
| Boleto e Pix na assinatura | Dependem da ativação na conta Stripe | Ligar por `STRIPE_PAYMENT_METHODS` sem mudar código |
| Página `/underconstruction` | Não é usada por nenhum menu | Remover na próxima limpeza |

## Migrações
- `aigov 0005`
- `accounts 0016`
- `billing 0008`

## Validação
- **Back:** 613 testes OK (suíte completa), incluindo `aigov/tests_routing.py`, `billing/tests_coupons.py` e
  `workflows/tests/test_email_action.py`.
- **Front:** 164 testes, lint sem erros, build OK.
- **E2E:**
  - login da equipe vai à Gestão;
  - ordem da IA trocada e salva, depois "Usar a recomendada";
  - cupom de dias extras criado na Gestão e aplicado no Perfil (teste estendido em 15 dias);
  - o mesmo cupom recusado na 2ª vez;
  - aviso de retorno do pagamento;
  - varredura de todas as telas com 4 perfis.
