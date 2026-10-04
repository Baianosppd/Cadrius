# Motor de IA do Cadrius: 3 provedores + motor local que aprende com o escritório (CAD-158)

> Decisão do produto: usar **as 3 IAs externas (OpenAI, Gemini, Groq)** e **construir um motor local** que aprende com cada escritório e propõe novas automações.
> Este documento define o que "motor local" significa tecnicamente, o que cabe no servidor atual e a ordem de construção. Análise crítica incluída.

## 1. A verdade técnica sobre "IA local que aprende"

"Aprender" tem três níveis, de menor para maior custo/risco:

| Nível | O que é | Precisa de GPU? | Quando faz sentido |
|---|---|---|---|
| **A. Memória + regras** (RAG, preferências, playbooks) | o sistema guarda decisões/peças/feedback do escritório, recupera por similaridade e **propõe regras** que o advogado aprova | **não** (CPU) | **agora** — já dá o efeito "aprende com o escritório" |
| **B. Modelos pequenos locais** (embeddings, classificadores, triagem) | modelos leves rodando no servidor para classificar, rotular e priorizar sem custo por chamada | não (CPU) | **agora/fase 4** |
| **C. LLM local de uso geral** (Llama/Qwen 7–8B via llama.cpp/Ollama) | gera texto no servidor; *fine-tuning* (LoRA) com dados aprovados do escritório | **recomendável** (CPU é lento) | quando houver volume e dados aprovados suficientes |

**Crítica honesta:** treinar/ajustar um LLM exige milhares de exemplos limpos *por tarefa*, GPU e avaliação contínua; antes disso o ganho vem de **A + B**.
Um LLM de 7–8B em CPU de VPS gera ~2–6 tokens/s: serve para triagem curta, **não** para minuta de peça. Por isso o plano é **híbrido**: o motor local decide/prepara e os 3 provedores externos geram o que exige capacidade.

## 2. Arquitetura proposta

```
 entrada (documento, e-mail, publicação, WhatsApp)
        │
   ┌────▼────────────── MOTOR CADRIUS (local, por escritório) ──────────────┐
   │ 1. Mascaramento de PII  →  2. Classificador/triagem (modelo pequeno)    │
   │ 3. Memória (pgvector): peças, decisões, playbooks do escritório          │
   │ 4. Roteador: escolhe  LOCAL | GROQ 8B | GEMINI Flash | OPENAI | premium  │
   │ 5. Guard (aigov): política, kill switch, limite, auditoria               │
   │ 6. Confiança + Matriz de autonomia (R0–R4) → executa | rascunho | pede   │
   └────┬─────────────────────────────────────────────────────────────────────┘
        │  feedback (aprovou / editou / rejeitou / desfez)
        ▼
   aprendizado: atualiza memória, propõe REGRAS ("Regras do escritório") e métricas
```

### Roteador de modelos (cheap-first com escalonamento)
| Tarefa | 1ª tentativa | Escala se | Premium |
|---|---|---|---|
| Triagem/classificação | **local** (modelo pequeno) | confiança < limiar → Groq 8B | — |
| Extração de documento | Groq 8B / Gemini Flash | validação do esquema falha ou confiança baixa → Gemini/OpenAI | — |
| Resumo de publicação | Gemini Flash / GPT mini | — | — |
| Minuta de peça | — | — | modelo premium + RAG do escritório |
| Pesquisa jurisprudencial | Gemini Flash com fontes | — | premium para casos complexos |

O `aigov.guard.check()` já valida política/provedor por escritório; o roteador entra **antes** dele e registra qual provedor atendeu (para custo e qualidade).

## 3. O que roda no servidor atual

* **Embeddings multilíngues pequenos** (ex.: `multilingual-e5-small`, ~120 MB, ONNX/`fastembed`) — **CPU, sem GPU, ~dezenas de ms por trecho**. É a peça central da memória.
* **Classificadores leves** (regressão logística/LightGBM sobre embeddings) para tipo de documento, urgência, área — treinam em segundos com os próprios dados do escritório.
* **pgvector** no PostgreSQL (autorizado para staging primeiro; ver `deploy/infra`).
* **LLM local (nível C)**: **não** colocar no VPS atual. Avaliar uma máquina dedicada (GPU ou CPU grande) quando houver demanda; até lá, os 3 provedores externos atendem.

## 4. Como o aprendizado funciona (sem treinar modelo de terceiros)

1. **Eventos de feedback** (`ai_feedback`): ação sugerida, contexto mascarado, decisão humana (aprovou/editou/rejeitou), diff da edição, tempo. Guardar o mínimo.
2. **Memória do escritório**: embeddings de peças modelo, contratos, e-mails relevantes, respostas aprovadas — **isolada por `organization_id`**, apagável (crypto-shredding).
3. **Few-shot dinâmico**: antes de chamar um provedor, busca os melhores exemplos aprovados do escritório e os inclui no prompt (estilo/linguagem do escritório) — sem *fine-tuning*.
4. **Regras aprendidas**: padrões repetidos viram **proposta de regra** ("intimações do TJSP: criar prazo de 15 dias úteis?"). **Só valem depois da aprovação do advogado** e ficam visíveis/desligáveis.
5. **Promoção de autonomia**: critérios objetivos (≥ N execuções, ≥ 95 % sem edição, 0 erro de prazo) → o sistema **sugere** subir o nível; **o sócio decide** (matriz R0–R4: peticionar, prazo fatal, pagamentos e exclusões **nunca** automáticos).
6. **Avaliação**: *golden set* por tarefa e escritório; regressão bloqueia promoção.
7. **(Futuro, opt-in contratual)** *fine-tuning* LoRA por escritório com dados aprovados, modelo isolado.

## 5. Privacidade e conformidade

* Nenhum dado de um escritório entra no contexto de outro; testes automatizados de isolamento do RAG.
* Provedores externos: contrato **sem retenção/treino** (zero data retention quando oferecido), lista permitida por escritório (já existe), DPA registrado em `privacy.Subprocessor`.
* LGPD art. 20: decisões automatizadas com impacto → revisão humana e explicação (fontes/trechos que embasaram).
* Tudo auditado em `AIActionLog` (sem conteúdo) e `AuditEvent`.

## 6. Ordem de construção (cards)

| Card | Entrega |
|---|---|
| CAD-183 | pgvector + tabela de memória por escritório + API de indexar/buscar (isolada) |
| CAD-182 | eventos `ai_feedback` + métricas de aceitação |
| CAD-158 | **provedor `LOCAL` no `aigov`** (allowed_providers) e roteador cheap-first |
| CAD-162 | classificador/extração com confiança e fila de revisão |
| CAD-184 | "Regras do escritório" (proposta → aprovação → vigência) |
| CAD-185 | promoção/rebaixamento de autonomia com auditoria |
| CAD-188 | golden sets e painel de qualidade |

## 7. Decisões pendentes

1. Reservar orçamento para uma máquina com GPU (ou CPU grande) para o nível C? Quando?
2. Quais provedores têm contrato sem retenção/treino hoje?
3. Piloto (escritório) para colher os primeiros dados de feedback — **ainda a definir**.
