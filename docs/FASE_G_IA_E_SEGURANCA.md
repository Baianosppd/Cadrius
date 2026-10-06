# Fase G (CAD-221) — IA funcionando, assistente com comandos, TI e cibersegurança

## 1. Provedores de IA
Todos passam por uma camada única (`aigov/llm.py`). O escritório escolhe quais permite em **Segurança → IA segura**.
A TI configura as chaves só no servidor (`.env`), **nunca por chat, e-mail ou GitHub**.

| Provedor | Gratuito? | Treina com os dados no plano gratuito? | Dados de cliente | Onde roda | Variável |
|---|---|---|---|---|---|
| **Claude (Anthropic)** | Não (pago por uso) | Não | Permitido | EUA | `ANTHROPIC_API_KEY` |
| **OpenAI** | Não | Não | Permitido | EUA | `OPENAI_API_KEY` |
| **Google Gemini** | **Sim** — Flash/Flash-Lite com limite diário | **Sim** | Bloqueado até `GEMINI_PAID=true` | EUA | `GEMINI_API_KEY` |
| **Groq (Llama)** | **Sim** — limite por minuto/dia | Não | Permitido | EUA | `GROQ_API_KEY` |
| **Mistral** | **Sim** — plano Experiment (telefone verificado) | **Sim** | Bloqueado até `MISTRAL_PAID=true` | União Europeia | `MISTRAL_API_KEY` |
| **OpenRouter** | **Sim** — modelos `:free` (50 pedidos/dia; 1.000 após comprar créditos) | **Sim** (varia) | Bloqueado com modelo `:free` | varia | `OPENROUTER_API_KEY` |
| **Maritaca Sabiá** (Brasil) | Não (barato, cobrado em R$) | Não | Permitido | **Brasil** | `MARITACA_API_KEY` |
| **Ollama (modelo local)** | **Sim** — roda no nosso servidor | Não (nada sai do servidor) | Permitido | servidor Cadrius | `OLLAMA_BASE_URL` |

Cerebras deixou de ter plano gratuito permanente em 16/07/2026 (só crédito inicial), por isso não entrou.

**Regra de sigilo (OAB/LGPD):** pedido com dado de cliente nunca vai para provedor que treina com os dados. Esses
provedores só atendem conteúdo genérico (ex.: marketing institucional da Cadrius).

**Ordem de uso** (o 1º disponível atende; se falhar, passa ao próximo):
- extração, triagem, minutas, marketing: barato primeiro — Groq, Gemini, Sabiá, Mistral, OpenAI, Claude, OpenRouter, Ollama (`AI_PROVIDER_ORDER`);
- assistente: qualidade primeiro — Claude, OpenAI, Gemini, Sabiá, Mistral, Groq, OpenRouter, Ollama (`AI_ASSISTANT_PROVIDER_ORDER`).

**Sugestão de começo:**
1. Grátis e seguro para dados de cliente: **Groq** (chave grátis) + **Ollama** num servidor com GPU/CPU suficiente.
2. Qualidade para o assistente e minutas: **Claude** ou **OpenAI** (pago por uso).
3. Dados no Brasil: **Sabiá**.

## 2. Assistente IA (`/assistente`)
- Conversa por pessoa (ninguém vê a conversa de outro); histórico cifrado no banco.
- **Consultas** (rodam na hora, só no escritório da pessoa): contatos, processos acompanhados, publicações, texto de
  publicação, agenda de prazos e tarefas, documentos, cálculo de prazo em dias úteis, financeiro (só dono/admin) e
  memória do escritório.
- **Ações** (só executam quando a própria pessoa confirma no cartão): criar tarefa, cadastrar contato, gerar minuta,
  lançar despesa, marcar publicação como revisada. Perfil "só leitura" não consegue.
- **Ferramentas de texto**: corrigir, formal, linguagem simples, resumir, e-mail, WhatsApp e extrair dados (partes,
  processo, datas, prazos, valores, pedidos). Também no botão "Escrever com IA" das minutas e do marketing.
- Proteções: texto de terceiros vai marcado como dado não confiável (contra instruções escondidas), kill switch e
  limite diário da política, créditos (`assistant_message` e `writing`), auditoria das ações.

## 3. Senha temporária pela TI
Gestão → Usuários → "Definir senha temporária (troca no próximo acesso)" (motivo obrigatório).
- A senha (16 caracteres) aparece **uma vez**; repasse por canal seguro (pessoalmente ou telefone), nunca junto com o login.
- Sessões abertas são encerradas e o bloqueio por tentativas é limpo.
- Com a senha temporária a pessoa só acessa a tela "Crie sua nova senha"; a API recusa o resto (403
  `password_change_required`) até a troca. A senha nunca vai para a auditoria — só o fato.

## 4. Cibersegurança (Gestão → Cibersegurança, área TI)
Nota 0–100 com o que resolver primeiro; saúde dos serviços; servidor (CPU, memória, disco, carga, rede, processo da
aplicação); PostgreSQL (conexões, consultas lentas, cache, deadlocks); Redis; fila; ameaças por hora (logins com falha,
negados/bloqueios), IPs e contas mais visadas, contas travadas; alertas de anomalia com triagem; acessos (sessões, MFA
da equipe e dos gestores, superusuários, contas sem uso há 90 dias, trilha de auditoria); proteções do servidor web e
verificações automáticas; IA (chave geral e provedores); **bloqueio de IP ou faixa** com prazo (redes internas e o
próprio IP da TI não podem ser bloqueados). Atualiza sozinha a cada 30 s.

Correção de segurança junto: o IP registrado na auditoria agora é o que o nosso proxy (Traefik) acrescenta ao
`X-Forwarded-For` (`AXES_PROXY_COUNT`), não o primeiro item, que o próprio cliente consegue falsificar.

## 5. Novas integrações
D4Sign e Clicksign (assinatura), Escavador (dados processuais), Notion, Pipedrive (CRM), Calendly (agendamento de
consultas), Slack e Microsoft Teams (avisos da equipe). Nova ação de automação: **avisar no chat da equipe**
(Slack, Teams ou Telegram) — a URL do webhook só é aceita nos domínios oficiais.

## Fontes
- [Free LLM APIs 2026 — OpenRouter](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/) · [Limites e pegadinhas dos planos gratuitos](https://continuumcode.ai/guides/free-llm-api/)
- [Gemini: plano gratuito usa os dados para melhorar produtos; pago não](https://flo2.com/blog/gemini-free-tier)
- [Maritaca AI — preços da API Sabiá](https://www.maritaca.ai/en/api)
