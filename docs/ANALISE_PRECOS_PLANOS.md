# Análise de preços, créditos e margem (CAD-156)

> Base: `scripts/pricing_model.py` (modelo reproduzível — **rode de novo quando mudar qualquer premissa**).
> **Todos os números são premissas**: preços de IA, Stripe e imposto mudam e custos fixos são estimativas. Antes de publicar preços,
> confirme (1) preços nos painéis dos provedores de IA, (2) contrato do Stripe, (3) alíquota com o contador, (4) custos fixos reais.

## 1. O que a conta mostra (conclusões)

1. **IA não é o gargalo de custo.** Uma extração padrão (≈ 6.000 tokens de entrada + 1.000 de saída) custa de **R$ 0,002 (Groq 8B)** a **R$ 0,025 (Gemini 2.5 Flash / GPT-3.5)**.
   Um plano de 1.500 créditos consome, no máximo, ~R$ 36 de IA mesmo com mistura pesada. O custo que pesa é **fixo (servidor, backup, e-mail, monitoramento), suporte, taxa de cartão, imposto e inadimplência**.
2. **O risco de prejuízo está nas operações caras, não nas baratas.** Minuta de peça com modelo premium custa ~R$ 0,67 cada. Uma minuta custa ~28× uma extração; se as duas valessem 1 crédito, o cliente que só gera peças esgotaria a margem do plano. Por isso **créditos têm peso por operação** (§3).
3. **O modelo atual (`gpt-3.5-turbo` por padrão) é o mais caro dos baratos e está defasado.** Para extração, `gpt-4o-mini`/equivalente atual custa ~1/3 e o Groq 8B ~1/12. Recomendação: **roteador "barato primeiro"** (§5).
4. **Ponto de equilíbrio:** com os custos fixos supostos (R$ 910/mês), bastam **~5 clientes PRO** ou **~7 clientes no mix 60/35/5** para cobrir o fixo. O que decide o lucro é **conversão do trial, churn e custo de aquisição**, não a conta de IA.
5. **Margem de contribuição por plano (uso 70 %, mistura típica): START ≈ 69 %, PRO ≈ 67 %, BUSINESS ≈ 64 %** — acima da meta de 60 %, mesmo no pior caso (mistura pesada, 100 % de uso: 65 % / 61 % / 55 %).

## 2. Resultado do modelo (premissas no topo do script)

```
Câmbio: R$ 5.60/US$ · Stripe 3.99% + R$ 0.39 · imposto 8%

## Custo de IA por operação (R$)
| Operação | Créditos | Modelo | Custo R$ | Custo/crédito R$ |
|---|---:|---|---:|---:|
| extração de documento | 1 | gemini-2.5-flash | 0.0241 | 0.0241 |
| triagem/classificação | 0.2 | groq llama-3.1-8b | 0.0005 | 0.0023 |
| resumo de andamento/publicação | 1 | openai gpt-4o-mini | 0.0042 | 0.0042 |
| rascunho de automação (IA) | 2 | gemini-2.5-flash | 0.0252 | 0.0126 |
| pesquisa jurisprudencial c/ resumo | 3 | gemini-2.5-flash | 0.0412 | 0.0137 |
| minuta de peça | 15 | modelo premium (peças) | 0.6720 | 0.0448 |

Custo médio por crédito — mistura típica: R$ 0.0173 · mistura pesada: R$ 0.0241

## Troca do modelo da extração padrão (6.000 tokens entrada + 1.000 saída)
| Modelo | R$/extração |
|---|---:|
| groq llama-3.1-8b | 0.0021 |
| openai gpt-4o-mini | 0.0084 |
| gemini-2.5-flash | 0.0241 |
| openai gpt-3.5-turbo (atual) | 0.0252 |

## Margem de contribuição por cliente/mês (depois de Stripe, imposto, IA e suporte)
| Plano | Preço | Uso dos créditos | Mistura | IA R$ | Contribuição R$ | Margem |
|---|---:|---:|---|---:|---:|---:|
| START (solo) | 99 | 30% | típica | 1.55 | 70.19 | 71% |
| START (solo) | 99 | 70% | típica | 3.62 | 68.12 | 69% |
| START (solo) | 99 | 100% | típica | 5.18 | 66.56 | 67% |
| START (solo) | 99 | 100% | pesada | 7.23 | 64.51 | 65% |
| PRO (escritório) | 299 | 30% | típica | 7.76 | 210.00 | 70% |
| PRO (escritório) | 299 | 70% | típica | 18.11 | 199.65 | 67% |
| PRO (escritório) | 299 | 100% | típica | 25.88 | 191.88 | 64% |
| PRO (escritório) | 299 | 100% | pesada | 36.15 | 181.61 | 61% |
| BUSINESS (grande) | 799 | 30% | típica | 31.05 | 551.76 | 69% |
| BUSINESS (grande) | 799 | 70% | típica | 72.45 | 510.36 | 64% |
| BUSINESS (grande) | 799 | 100% | típica | 103.50 | 479.31 | 60% |
| BUSINESS (grande) | 799 | 100% | pesada | 144.59 | 438.22 | 55% |

## Pacotes de créditos avulsos (compra extra; validade 12 meses)
| Pacote | Preço | R$/crédito | Custo IA (mistura pesada) | Margem após taxas+imposto |
|---|---:|---:|---:|---:|
| 200 créditos | 59 | 0.295 | 4.82 | 79% |
| 1.000 créditos | 199 | 0.199 | 24.10 | 76% |
| 5.000 créditos | 799 | 0.160 | 120.49 | 73% |

## Ponto de equilíbrio (custos fixos R$ 910/mês)
| Mix de clientes | Contribuição/mês | Clientes p/ cobrir o fixo |
|---|---:|---:|
| só START | 68 | 13.4 |
| só PRO | 200 | 4.6 |
| 60% START / 35% PRO / 5% BUSINESS | 136 | 6.7 |
```

## 3. Créditos com peso por operação (para nunca dar prejuízo)

| Operação | Créditos | Por quê |
|---|---:|---|
| Extração de documento (≤ 20 mil caracteres) | 1 | unidade base (hoje já é 1) |
| Triagem/classificação, busca semântica | 0,2 | modelo pequeno/local |
| Resumo de andamento ou publicação | 1 | |
| Rascunho de automação por IA | 2 | |
| Pesquisa jurisprudencial com resumo | 3 | entrada longa |
| **Minuta de peça** | **15** | saída longa, modelo premium |
| OCR de página escaneada | 0,5/pág. | local = custo de CPU; serviço pago = repassar |

Regra: **o peso é configurável por operação** e revisado quando o preço do provedor mudar. O consumo de cada operação já passa por `consume_credit(amount=…)`.

## 4. Planos propostos (valores a validar pela diretoria)

| | **TRIAL** | **START** | **PRO** | **BUSINESS** |
|---|---|---|---|---|
| Para quem | testar | advogado solo | escritório pequeno | escritório grande |
| Preço/mês | R$ 0 (14 dias, sem cartão) | **R$ 99** | **R$ 299** | **R$ 799** (sob consulta acima de 20 usuários) |
| Usuários | 1 | 1 | 5 | 20 |
| Créditos/mês | 30 (uso único) | 300 | 1.500 | 6.000 |
| R$/crédito incluso | — | 0,33 | 0,20 | 0,13 |
| Limite por membro (dono ajusta) | — | — | sim | sim |
| SSO, ERP (Astrea/Projuris), suporte prioritário | — | — | ERP básico | sim |
| Desconto anual | — | 2 meses grátis | 2 meses grátis | negociável |

* **Por que degraus de preço/crédito decrescentes:** quem compra mais paga menos por crédito, mas o preço por crédito de **qualquer plano é ≥ 4× o custo real de IA** (R$ 0,13 vs R$ 0,024 no pior caso médio).
* **O dono distribui créditos entre os membros** (já implementado: `credit_limit` por membro; nunca excede o total do plano).

### Créditos avulsos (compra extra) — o que o cliente "adiciona"

| Pacote | Preço | R$/crédito | Margem (após taxa e imposto, mistura pesada) |
|---|---:|---:|---:|
| 200 créditos | R$ 59 | 0,295 | ~79 % |
| 1.000 créditos | R$ 199 | 0,199 | ~76 % |
| 5.000 créditos | R$ 799 | 0,160 | ~73 % |

* Pacote avulso **custa mais por crédito que o plano** (incentiva upgrade), **vale 12 meses** e é **consumido depois** dos créditos mensais do plano.
* Os créditos do plano **não acumulam** (zeram no ciclo); os avulsos sim — evita "estoque" barato eterno e passivo contábil.
* Aviso ao dono em 80 % e 100 % do total e por membro; compra de pacote em 1 clique (Stripe Checkout `mode=payment`).

## 5. Como manter o custo baixo (alavancas técnicas)

1. **Roteador de modelos por tarefa**: triagem → local/Groq 8B; extração → modelo barato com *fallback* para o intermediário quando a confiança for baixa; minuta → premium. Economia esperada (estimativa a medir em produção): metade ou mais do custo de IA.
2. **Cache de resultados** (hash do documento) — reprocessar o mesmo arquivo não cobra nem gasta.
3. **Mascarar e cortar entrada** (já limitada a 20 mil caracteres): enviar só o trecho necessário.
4. **Motor local** (`docs/MOTOR_IA_LOCAL.md`): triagem, classificação e embeddings sem custo por chamada.
5. **Limites por plano**: `daily_ai_request_limit` e `max_actions_per_ai_workflow` já existem; ligá-los ao plano.
6. **Alertas de custo**: painel interno com gasto de IA por escritório/dia; alarme se > 2× o previsto.

## 6. Política de trial e inadimplência (recomendação)

**Trial:** 14 dias, 30 créditos, sem cartão, 1 usuário; no fim vira "somente leitura" até assinar. Custo por trial ≈ R$ 1 (IA) + suporte; com 20 % de conversão o custo efetivo de aquisição por assinante é pequeno.

**Cobrança que falha (Stripe Smart Retries, ~2 semanas):**
| Dia | Estado | O que acontece |
|---|---|---|
| 0 | `past_due` | aviso por e-mail ao dono; tudo funciona |
| 1–7 | carência | banner no app; tentativas automáticas de cobrança |
| 8–14 | restrito | IA e automações pausadas; leitura/exportação liberadas |
| 15–30 | suspenso | só login e **exportação dos dados** (LGPD); sem IA |
| > 30 | cancelado | retenção legal; aviso de eliminação conforme a política de retenção |

Nunca apagar dados por inadimplência antes do prazo de retenção; sempre permitir **exportar**.

## 7. Impostos e taxas a confirmar

* Stripe Brasil: cartão ≈ 3,99 % + R$ 0,39 (confirmar contrato); PIX/boleto têm taxas diferentes — considerar PIX para anual.
* Imposto: premissa 8 % (Simples Nacional); **o enquadramento (anexo/faixa) muda a margem** — validar com o contador, incluindo ISS por município.
* Nota fiscal de serviço por assinatura (integração com emissor) — não incluída no custo acima.

## 8. Sensibilidades (o que mudaria a conclusão)

| Se… | Efeito |
|---|---|
| uso real ≫ planejado (clientes só geram peças) | margem BUSINESS cai para ~55 % (tabela "pesada"); subir peso da minuta ou criar plano com cota de peças |
| preço do provedor dobrar | IA sobe de R$ 36 para R$ 72 no PRO (uso 100 %, mistura pesada): margem ~49 %; trocar roteamento |
| churn alto (> 5 %/mês) | LTV cai; investir em onboarding e módulos que "prendem" (ERP, agenda, aprendizado do escritório) |
| inadimplência 5 % | −5 p.p. de receita; mitigar com anual/PIX e cobrança com retentativas |
| OCR pago (serviço externo) | custo por página sobe; **repassar em créditos** (0,5–1/pág.) |

## 9. Decisões para fechar

1. Valores finais dos planos (tabela §4) e se haverá plano anual.
2. Trial: 14 dias/30 créditos ok? Exigir cartão no trial?
3. Política de inadimplência da §6 ok (7/14/30 dias)?
4. Pesos de créditos por operação (§3).
5. Módulos extras vendidos à parte: **Pesquisa (Jusbrasil e afins)** — ver `docs/MODULO_JUSBRASIL.md`.
