# Estudo: qual IA em cada atividade do Cadrius (CAD-224)

**Pedido:** separar as IAs pelas atividades em que mais rendem, com o Claude nas automações e as demais em geração de
texto e outras tarefas. A escolha fica configurável na Gestão, e se uma IA cair outra assume.

## 1. Onde configurar
Em **Gestão Cadrius → IA por atividade** (área TI):
- Cada atividade tem uma **cadeia em ordem**: a primeira IA atende e, se falhar, a próxima assume na mesma hora.
- A opção **"usar as demais como reserva"** entra no fim, quando toda a cadeia falha.
- O botão **"Usar a recomendada"** volta ao que está neste estudo.
- A **saúde de cada IA** aparece na tela: "ok", falhas ou "fora (reserva assume)".
- Toda troca fica na auditoria (`ai.route_changed`).
- O diagnóstico também aparece no terminal: `python manage.py cadrius_ia_provedores`.

## 2. Recomendação (padrão de fábrica)

| Atividade | Onde é usada no Cadrius | Cadeia recomendada | Por quê |
|---|---|---|---|
| **Automações e assistente** | Assistente IA com ferramentas, criação de regras e fluxos pela IA, conector Claude/ChatGPT | **Claude** > OpenAI > Gemini > Sabiá > Groq > Ollama | Precisa acertar chamadas de ferramenta em várias etapas. Claude liderou o BFCL v4 (tool calling) em 2026 e teve a melhor nota no oab-bench. |
| **Estratégia de caso** | Modo estratégia de caso | **Claude** > OpenAI > Gemini > Sabiá | Raciocínio longo, citação de fontes e menor tolerância a erro. |
| **Redação jurídica** | Minutas, ferramentas de texto (corrigir, formalizar, resumir), e-mails e mensagens ao cliente | **Sabiá (Maritaca)** > Claude > OpenAI > Gemini > Mistral > Groq > Ollama | Treinado em português do Brasil, com desempenho comparável ao GPT-4o em 64 exames brasileiros (OAB inclusive). Processa no **Brasil** e custa de 3 a 4 vezes menos. |
| **Leitura de documentos** | Leitura de intimações e documentos (prazos, partes, valores) e triagem de publicações | **OpenAI** > Gemini > Claude > Groq > Sabiá > Mistral > Ollama | Precisa de JSON válido e estável em volume, com custo baixo. |
| **Triagem e classificação** | Triagem de e-mails | **Groq (Llama 70B)** > Gemini > OpenAI > Sabiá > Mistral > Ollama | Muito volume e resposta curta. Groq roda o Llama 70B a centenas de tokens por segundo, por US$ 0,59/0,79 por milhão de tokens. |
| **Marketing** | Ideias e textos institucionais, sem dado de cliente | **Gemini** > Groq > Mistral > OpenAI > Claude > Sabiá | Texto criativo sem sigilo, que pode usar planos gratuitos. |

## 3. O que nunca muda, qualquer que seja a configuração
1. **Sigilo e LGPD:** IA cujo plano gratuito treina com os dados (Gemini grátis, Mistral Experiment, OpenRouter
   `:free`) **não recebe dado de cliente**, mesmo que esteja no topo da cadeia. Ela é pulada.
2. **Política do escritório:** cada escritório escolhe quais IAs aceita, em Segurança → IA segura.
3. **Chave própria (BYOK):** se o escritório cadastrou a própria chave em Plugins, ela vem primeiro para ele e não
   consome créditos.
4. **Kill switch:** a chave geral da Gestão desliga toda a IA.

## 4. Quando uma IA cai
- **Na hora:** erro de rede, chave inválida, limite ou resposta fora do formato fazem a **próxima da cadeia** assumir
  na mesma requisição. Vale para o assistente, para a leitura de documentos, minutas, triagem, marketing e fluxos.
- **Disjuntor:** depois de **3 falhas seguidas**, a IA vai para o fim da fila por **5 minutos**, para não atrasar
  ninguém, e volta sozinha. A tela da Gestão mostra "fora (reserva assume)".
- **Sem nenhuma IA disponível:** a leitura de documentos cai na **leitura local** (sem IA), e as demais telas avisam o
  usuário com uma mensagem clara.

## 5. Custos e modelos
- **Modelo de cada provedor:** é definido no `.env` (`ANTHROPIC_MODEL`, `OPENAI_MODEL`, `MARITACA_MODEL`…).
- **Claude nas automações:** para economizar sem perder muito em ferramentas, dá para usar um modelo intermediário do
  Claude em `ANTHROPIC_MODEL`. O padrão é o mais capaz.
- **Ordem de começo sugerida, por custo:**
  1. **Claude**: automações e estratégia.
  2. **Sabiá**: redação.
  3. **OpenAI mini**: leitura.
  4. **Groq**: triagem (grátis com limite).
  5. **Gemini**: marketing (grátis).

  Com essas cinco chaves, cada atividade tem pelo menos 2 reservas.

## Fontes
- [BFCL v4 — Berkeley Function Calling Leaderboard (2026)](https://benchlm.ai/benchmarks/bfclV4) · [Epoch AI — revisão do BFCL](https://epoch.ai/benchmarks/berkeley-function-calling-leaderboard/review)
- [Sabiá-3 — relatório técnico (arXiv 2410.12049)](https://arxiv.org/pdf/2410.12049v3) · [Sabiá-3: OAB/CPNU/Revalida](https://docs.adapta.org/modelos-de-texto/sabia-3) · [oab-bench — avaliação de escrita jurídica](https://www.themoonlight.io/review/automatic-legal-writing-evaluation-of-llms)
- [Groq — Llama 3.3 70B velocidade](https://www.gmicloud.ai/en/blog/llama-70b-llama-4-inference-speed) · [Groq — preços (jun/2026)](https://www.aipricing.guru/groq-pricing/)
- [Gemini 2.5 Flash — saída estruturada e preço](https://modelcompare.dev/pt/models/google/gemini-2-5-flash)
