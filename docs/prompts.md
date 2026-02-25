# Prompts de Extração de Dados com IA (ChatGPT)

Este documento detalha os templates de prompt e a estratégia de comunicação usados pelo módulo `extraction/ai_wrapper.py` para extrair dados estruturados de e-mails, com base nos Schemas Pydantic.

## 1. Estratégia de Prompt Base

O `ai_wrapper.py` utiliza uma abordagem de **System Prompt** com **JSON Schema Injection** para forçar a saída estruturada.

**Objetivo:** Minimizar tokens e maximizar a aderência ao JSON Schema.

| Componente | Conteúdo (Template) | Proprietário |
| :--- | :--- | :--- |
| **System Role** | "Você é um extrator de dados altamente eficiente. Sua única tarefa é analisar o texto fornecido e retornar os dados estritamente no formato JSON, conforme o schema abaixo. Não adicione nenhum comentário ou texto explicativo fora do objeto JSON." | Juliano |
| **Schema Injection** | `SCHEMA JSON: {json.dumps(schema_json)}` (O JSON Schema é gerado pelo Pydantic.) | Juliano |
| **User Message** | Combinação do **Prompt Template Específico** + o **Corpo do Email** (`TEXTO DE ENTRADA: --- {text}`). | Juliano |

## 2. Template Específico: Pedido de Serviço (SERVICE_ORDER)

Este template é usado quando o sistema detecta (ou o prompt inicial tenta extrair) informações relacionadas a um novo pedido ou projeto.

**Schema Pydantic Alvo:** `extraction.schemas.ServiceOrderSchema`

**Propósito:** Extrair metadados críticos como Nome do Cliente, Serviço e Prazo Sugerido (SLA).



**Estratégia Few-Shot (Opcional):**
* **Exemplo 1 (HIGH):** Se o cliente usar palavras como "urgente", "imediato" ou "parado".
* **Exemplo 2 (LOW):** Se o cliente perguntar apenas sobre preço ou futura implementação.

## 3. Template Específico: Solicitação de Suporte/Bug (SUPPORT_REQUEST)

Este template foca na extração de informações para criar um ticket de suporte no Trello, visando a classificação rápida de incidentes.

**Schema Pydantic Alvo:** `extraction.schemas.SupportRequestSchema`

**Propósito:** Identificar o sistema afetado e determinar a criticidade do incidente.



## 4. Estratégia de Fallback (Juliano)

Se a IA falhar na primeira tentativa de validação Pydantic (`ValidationError` ou `JSONDecodeError`), o `ai_wrapper.py` (Juliano) implementa até **2 tentativas de re-prompt** antes de falhar:

1.  **Tentativa 1:** Reenvia o prompt original **adicionando** a mensagem de erro da validação Pydantic, instruindo a IA a corrigir o JSON.
2.  **Tentativa 2 (Se necessário):** Reenvia o prompt, enfatizando a necessidade de **apenas JSON**.
3.  **Falha Final:** Se falhar após as retentativas, a função retorna `None`, e o *worker* de **Thales** marca o `EmailMessage` como `REQUIRES_REVIEW` no banco de dados de **Jullio**.

---

Com este documento, finalizamos todos os artefatos essenciais de arquitetura e base para que o desenvolvimento possa começar de forma paralela e integrada:

1.  **Jullio:** Estrutura, Modelos, Autenticação JWT e Endpoints (validados pelos testes básicos).
2.  **Thales:** Workers, Integrações (IMAP, Trello/Telegram) e Logs de Rastreamento.
3.  **Juliano:** Wrappers de IA, Schemas Pydantic e Documentação de Prompts.

O próximo passo no plano original seria a **Integração Pontual** e os **Testes E2E**.

**A pergunta final é:** O time está pronto para iniciar o desenvolvimento nas *feature branches* e focar na implementação do código (*coding*)?


