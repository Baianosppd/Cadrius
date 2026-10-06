# Fase H (CAD-222) — IA ligada pelo `.env`, plugins, hiperautomação, estratégia de caso e Agenda Google

## 1. Colocar as chaves no `.env` já liga a IA?
Sim, depois do deploy desta versão e destes passos:
1. Merge e deploy. O rebuild instala as bibliotecas novas (`anthropic`, `psutil`) e as migrações rodam sozinhas ao subir o `web`.
2. Colocar as chaves em `/opt/cadrius/{prod,staging}/.env`. Os nomes estão em `deploy/app/env.backend.template`.
   **Nunca envie chaves por chat, e-mail ou GitHub.**
3. Rodar `docker compose up -d --force-recreate web worker`. O `env_file` repassa todas as variáveis ao web e ao worker.
4. Liberar o provedor para os escritórios que já existem. Por padrão o escritório só usa o que foi liberado (LGPD).
   O dono pode liberar em **Segurança → IA segura**, ou a TI pode rodar:
   `python manage.py cadrius_ia_provedores --liberar ANTHROPIC[,OPENAI] [--escritorio <uuid>]`
5. Conferir três coisas:
   - a chave geral de IA está ligada;
   - a IA está ativa no escritório;
   - o escritório tem créditos (quem usa chave própria não consome créditos).
6. Diagnóstico: `python manage.py cadrius_ia_provedores`. Ele mostra quais provedores têm chave, se treinam com os
   dados e quais escritórios liberaram cada um. Os valores das chaves nunca aparecem.

Provedores gratuitos que treinam com os dados (Gemini grátis, Mistral Experiment, OpenRouter `:free`) **nunca recebem
dado de cliente**.

## 2. Plugins (menu **Plugins (Claude, ChatGPT)**)
### Conector do Cadrius (MCP)
Quem já paga Claude Pro/Max/Team ou ChatGPT pode usar o Cadrius de dentro dessas ferramentas.

- **Endereço:** `https://<api>/mcp/`, com o cabeçalho `Authorization: Bearer cdr_…`. Para clientes que não aceitam
  cabeçalho, use `https://<api>/mcp/<token>/`.
- **Passo a passo:** a tela mostra as instruções para:
  - Claude (Configurações → Conectores → Adicionar conector personalizado);
  - ChatGPT (modo desenvolvedor);
  - Claude Code (`claude mcp add --transport http …`).
- **Tokens:**
  - pessoais, até 5 por pessoa, válidos por 1 ano e revogáveis;
  - aparecem uma única vez, e o banco guarda só o hash;
  - limite de 120 chamadas por minuto, cada chamada auditada (`assistant.mcp_call`).
- **Permissão "Só consultar":** contatos, processos, publicações, agenda, documentos, prazos e finanças (só para quem
  já pode ver finanças).
- **Permissão "Consulta e pedidos":** ações (tarefa, minuta, mensagem ao cliente…) **não executam** pelo conector.
  Elas viram um pedido em **Assistente IA → "Pedidos pelo conector"**, avisado no sino, e só rodam quando a pessoa
  confirma.
- **Desligar:** o dono ou admin liga e desliga o conector em Assistente → Configurações. Desligar revoga todos os
  tokens.

### Conta de IA do escritório (traga sua chave)
- O escritório cadastra uma chave própria (Claude, OpenAI, Gemini, Groq, Mistral, Sabiá, OpenRouter ou Ollama).
- A chave fica cifrada, aparece só pelo final (…1234) e pode ser testada pela tela.
- O Cadrius usa essa chave primeiro e **não consome créditos**.
- Ollama só é aceito com `https` e endereço público (proteção contra SSRF).
- **Atenção:** a assinatura Claude Pro do claude.ai **não inclui API**. Para usar o Pro, o caminho é o conector acima.
  Uma chave de API é criada à parte em console.anthropic.com e é cobrada por uso.

## 3. Assistente como auxiliar de tudo (hiperautomação)
- **Automação:**
  - ver o catálogo, listar e criar regras, mostrando uma prévia de gatilho, condições e ações;
  - ativar regras depois de simular;
  - aceitar sugestões da IA.
  - Criar e ativar regras é só para dono ou admin, e toda regra nasce desligada.
- **Memória e perfil:**
  - "lembrar" grava uma nota na memória do escritório (dado sensível é mascarado);
  - as respostas usam a memória (RAG), que é tratada como dado não confiável;
  - o perfil do escritório é consultável.
- **Rotina:**
  - oportunidades do funil e criação de oportunidade;
  - honorários em aberto;
  - avisar o cliente pelo melhor canal, com prévia do canal;
  - e-mails triados;
  - compromissos da Agenda Google.
- **Advogado autônomo** (pessoa física sozinha na conta):
  - tem todas as ferramentas;
  - o menu troca "Equipe" por "Convidar alguém" (ou esconde quando o plano tem 1 usuário);
  - os primeiros passos e o assistente não falam de equipe.

## 4. Modo estratégia de caso (opcional)
- **Ligar:** o dono ou admin liga em Assistente → Configurações → "Estratégia de caso". Depois, "Estratégia de caso"
  → escolher o processo.
- **Como o chat trabalha:** usa o contexto do processo (partes, andamentos, prazos, publicações, documentos) e ajuda a
  montar fatos, teses, provas, riscos, cenários e plano de ação. Ele cita as fontes e avisa quando falta informação.
- **Plano salvo:** "salvar plano" grava o plano em **Minutas** (modelo `assistente:plano_do_caso`) para revisão.

## 5. Novos gatilhos de automação
| Gatilho | Quando | Exemplo de modelo pronto |
|---|---|---|
| E-mail recebido (triado) | e-mail novo numa caixa conectada, já classificado | intimação → tarefa urgente; cliente escreveu → tarefa "Responder"; contato comercial → aviso |
| Compromisso da Agenda Google chegando | N dias antes (a partir das 8h) | lembrar o cliente da audiência 1 dia antes; avisar a equipe 2 dias antes do prazo |
| Tarefa atrasada | N dias após o vencimento | aviso ao responsável |
| Pagamento recebido | parcela marcada como paga | agradecimento ao cliente |
| Oportunidade mudou de etapa | funil | confirmação da reunião |
| Contrato/acordo criado | carteira | boas-vindas |
| Documento enviado | upload | — |
| Cliente abriu o portal | portal (no máximo 1 por hora) | — |

**Nova ação "Avisar o cliente (melhor canal autorizado)"**:
- **Escolha do canal:**
  - *melhor*: WhatsApp se o cliente autorizou e o escritório tem WhatsApp conectado; senão, e-mail autorizado;
  - também dá para forçar WhatsApp ou e-mail.
- **Quando não envia:** se o cliente pediu para não receber (opt-out) ou não deu consentimento, nada é enviado e o
  motivo fica no histórico.
- **Horário comercial:** só envia entre 8h e 20h, de segunda a sábado, fora dos feriados nacionais. Fora disso, o passo
  fica "agendado" e é retomado sozinho no próximo horário útil.
- **Aprovação:** mensagens a clientes continuam passando pela aprovação da equipe (padrão das regras).

## 6. Triagem de e-mails
Cada e-mail novo é classificado em duas etapas:
1. **Regras primeiro**: remetentes de tribunal, palavras de intimação, contato cadastrado, pedidos de orçamento,
   datas citadas.
2. **IA depois**, só com provedores seguros para dado de cliente.

O resultado tem:
- categoria (intimação, cliente, agenda, financeiro, comercial, documento, marketing, outro);
- urgência e resumo (cifrado);
- ação sugerida e data citada;
- contato vinculado.

A triagem dispara o gatilho "E-mail recebido" uma única vez por e-mail. Mensagens de clientes nunca viram intimação ou
comercial só por citar "sentença" ou "orçamento".

## 7. Google Agenda: compromissos e prazos criados direto no Google
Em Integrações → Google Agenda, quando conectado:

- **O que é trazido:** prazos, audiências, perícias e reuniões dos próximos N dias (30, 60, 90 ou 180). Eventos criados
  pelo próprio Cadrius não são trazidos de novo.
- **Classificação:** por palavras-chave, com correção manual do tipo na tabela (a correção não é desfeita na próxima
  sincronização).
- **Vínculos:** o número CNJ no título vincula o processo acompanhado, e o e-mail do convidado vincula o contato.
- **Tarefas:** os tipos escolhidos viram tarefa no Cadrius. "Prazo:" entra no gatilho "Prazo chegando" e não volta
  duplicado ao Google.
- **Eventos cancelados ou apagados** no Google são marcados e não disparam mais alertas.
- **Alertas prontos com um clique:**
  - lembrar o cliente da audiência 1 dia antes (melhor canal, horário comercial, aprovação);
  - avisar a equipe 2 dias antes de cada prazo.
  - Outras combinações de canal, antecedência e texto podem ser feitas em Automações → Nova regra → "Compromisso da
    Agenda Google chegando".

## 8. Validação
- **Back:** 570 testes OK, incluindo `automations/tests_h.py` e `assistant/tests_h.py`.
- **Front:** 157 testes, lint sem erros, build OK.
- **E2E (Playwright):**
  - plugins/MCP (initialize, tools/list, consulta, pedido → confirmação no Assistente);
  - chave própria;
  - assistente criando automação;
  - estratégia de caso;
  - Agenda Google com alerta;
  - editor de regras;
  - advogado autônomo.
  - A IA usada foi um modelo local falso compatível com OpenAI, sem custo nem dado real.
