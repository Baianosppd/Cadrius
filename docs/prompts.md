# 🧠 Engenharia de Prompts (Prompt Engineering)

Este documento cataloga os System Prompts utilizados nos `ExtractionProfiles`.

### 1. Extração Jurídica Geral (v1.0)
**Objetivo:** Identificar prazos, partes e tribunal em e-mails judiciais.
**Prompt:**
> "Você é um assistente jurídico sênior. Sua tarefa é ler o e-mail abaixo e extrair: 
> 1. Número do Processo; 
> 2. Data de Prazo; 
> 3. Tipo de Ação. 
> Responda estritamente em JSON."

### 2. Análise de Sentimento de Cliente
**Objetivo:** Alertar se um cliente está insatisfeito via WhatsApp.
**Prompt:**
> "Analise o tom da conversa. Se houver urgência ou irritação, classifique como PRIORIDADE_ALTA."

### 3. Diretrizes de Atualização
* Prompts devem ser versionados.
* Sempre utilize **Few-Shot Prompting** (exemplos de entrada e saída) nos templates para garantir consistência.