# Módulo de Pesquisa Jurídica (Jusbrasil e fontes) — análise crítica de custo e implementação (CAD-157)

> O contato comercial com o Jusbrasil é conduzido por nós (Cadrius). **Nada aqui assume preço ou capacidade da API do Jusbrasil**: os valores
> abaixo são hipóteses para dimensionar o negócio até haver proposta formal. Confirme escopo, preço, limites e **autorização de uso/armazenamento/revenda** por contrato.

## 1. Resumo executivo

* **Vender como módulo extra** ("Pesquisa Pro"), não embutido nos planos: o custo é **por consulta/processo monitorado** (cresce com o uso) e depende de contrato de terceiro.
* **Começar sem o Jusbrasil** com fontes oficiais gratuitas que já cobrem o essencial do monitoramento (DataJud/CNJ, DJEN/Comunica PJe, DOU, LexML, feeds de tribunais) — e tratar o Jusbrasil como **camada premium** (jurisprudência/doutrina/diários agregados) quando o contrato estiver assinado.
* **Risco nº 1 é jurídico/contratual** (redistribuir conteúdo de terceiros, armazenar, repassar a clientes), não técnico. **Sem scraping** (viola termos; pode gerar bloqueio e responsabilidade).

## 2. Opções para o mesmo dado (comparação)

| Fonte | Cobre | Custo | Observações |
|---|---|---|---|
| **DataJud (CNJ)** | metadados e movimentações de processos | grátis (API pública) | não traz inteiro teor; cobertura/atualização variam por tribunal [VALIDAR] |
| **DJEN / Comunica PJe (CNJ)** | comunicações/intimações por OAB, nome, processo | grátis | base do "recorte de publicações" [VALIDAR contrato de uso] |
| **DOU / diários** (Imprensa Nacional) | publicações oficiais | grátis | formatos variam |
| **LexML / Planalto / STF-STJ-TST** | legislação, jurisprudência dos tribunais superiores | grátis | pesquisa limitada; bom para citação com fonte |
| **Escavador / Digesto / similares** | agregação, monitoramento, tribunais variados | pago (API) | alternativa ao Jusbrasil; comparar preço e termos |
| **Jusbrasil** | jurisprudência, diários, monitoramento, doutrina | pago (contrato) | confirmar existência/escopo de API e se permite uso embarcado |

## 3. Modelo de custo (hipotético — substituir pelos valores da proposta)

Variáveis: `P` = custo por processo monitorado/mês, `N` = processos por cliente, `F` = mensalidade fixa do contrato, `C` = nº de clientes no módulo,
taxas (cartão 4 %) e imposto (8 %), margem-alvo 65 %.

Preço mínimo do add-on por cliente = `(N·P + F/C) / (1 − taxas − imposto − margem)`

| Cenário (hipotético) | N | P (R$) | F (R$/mês) | C | Custo/cliente | Preço mínimo/mês |
|---|---:|---:|---:|---:|---:|---:|
| Pequeno | 50 | 0,50 | 0 | — | 25 | ~R$ 90 |
| Médio | 200 | 1,00 | 500 | 20 | 225 | ~R$ 800 |
| Grande | 1.000 | 1,50 | 1.500 | 20 | 1.575 | ~R$ 5.600 |

Leitura crítica: **o custo escala com o nº de processos**; se o preço do add-on for fixo, o cliente grande dá prejuízo. Portanto: **cobrar por faixa de processos monitorados** (ex.: até 50 / 200 / 1.000) e/ou repassar em "créditos de pesquisa".
O módulo só fica atraente se o custo por processo for baixo **ou** se o cliente trouxer a própria credencial (BYOK, §4).

## 4. Modelos comerciais possíveis

1. **Add-on por faixa** (recomendado): "Pesquisa Pro" com faixas de processos monitorados e pesquisa jurisprudencial inclusa até X consultas/mês.
2. **BYOK (traga sua chave)**: o escritório conecta a **própria** conta/credencial do provedor (Jusbrasil, Escavador…). Custo e licença são do cliente; o Cadrius só orquestra e resume com IA. **Menor risco contratual e zero custo de dado para nós.**
3. **Revenda/parceria**: contrato de reseller com o provedor (margem sobre o repasse). Maior receita, maior exigência contratual e de suporte.
4. **Só fontes gratuitas** no plano base + Jusbrasil no add-on.

Recomendação: **(4) agora → (2) assim que houver conector → (1/3) após proposta formal**.

## 5. Como implementar (técnico)

```
SearchProvider (interface): search(query, filtros) · fetch(id) · subscribe(processo|termo|OAB) · health() · quota()
   ├─ DataJudProvider      (grátis)        ├─ DjenProvider (grátis)      ├─ DouProvider (grátis)
   ├─ LexMLProvider        (grátis)        ├─ NewsRssProvider (feeds autorizados)
   ├─ EscavadorProvider    (pago, BYOK/contrato)
   └─ JusbrasilProvider    (pago, só após contrato; BYOK ou chave da empresa)
```
* **Orquestrador** com cache (Redis; TTL por tipo), *rate limit* por provedor, *circuit breaker*, e **medição de uso por escritório** (`SearchUsage`) para cobrar/limitar por faixa.
* **Credenciais** do cliente (BYOK) em `AppConnection.credentials` (cifrado). Chave da empresa só no `.env` do servidor.
* **Resumo por IA com citação obrigatória**: o resultado mostra a fonte e o link; sem fonte, a IA não afirma (evita "alucinar" ementas/números).
* **Normalização**: número CNJ (validação do dígito verificador), tribunal, classe, partes, datas — um modelo `Case`/`CaseEvent` comum a todos os provedores.
* **Deduplicação** de andamentos por hash; **alertas** ao advogado responsável; ligação com **prazos** e **Google Calendar**.
* **LGPD**: consulta por nome de pessoa é tratamento de dado pessoal de terceiros — finalidade restrita ao mandato, trilha de quem consultou o quê, minimização no cache, respeito a segredo de justiça.
* **Feature flag por plano**: o módulo liga por escritório (`organization.modules`).

## 6. Plano de ação (comercial + técnico)

| # | Ação | Resp. | Saída |
|---|---|---|---|
| 1 | Pedir proposta ao Jusbrasil (e a 1–2 concorrentes) com as perguntas da §7 | Jullio | proposta escrita |
| 2 | Implementar a interface + DataJud + DJEN + notícias (grátis) | Thales | monitoramento básico em staging |
| 3 | Medição de uso e faixas no billing | Thales | `SearchUsage`, limites por plano |
| 4 | Conector BYOK (Jusbrasil/Escavador) conforme API disponível | Thales | conector sob feature flag |
| 5 | Piloto com 1 escritório (a definir) e ajuste de preço da faixa | todos | preço final do add-on |

## 7. Perguntas para a proposta (checklist de negociação)

1. Existe API para integrar terceiros? Quais recursos (monitoramento de processo, diários, jurisprudência, inteiro teor)?
2. Modelo de preço: por consulta, por processo monitorado, por usuário, mensalidade fixa? Franquia e excedente?
3. Limites de uso (req/s, req/dia) e SLA; sandbox para homologação?
4. **Pode-se armazenar, indexar e resumir por IA o conteúdo retornado? Por quanto tempo? Pode-se exibir a terceiros (clientes do escritório)?**
5. Pode-se revender/embutir no Cadrius (white-label) ou só BYOK?
6. Responsabilidade e LGPD: papel de cada parte (operador/controlador), DPA, subprocessadores, local de armazenamento.
7. Prazo de contrato, reajuste, rescisão e propriedade dos dados gerados pelo cliente.
