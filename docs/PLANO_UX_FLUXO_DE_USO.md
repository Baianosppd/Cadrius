# Plano de UX (CAD-226): o Cadrius mudando o jeito de trabalhar, com conforto

**Objetivo:** o advogado abre o Cadrius e, em poucos minutos, entende o que o sistema faz por ele, liga a primeira
automação vendo o fluxo rodar e passa a pedir as coisas à IA em vez de fazer à mão.

**Princípios:**
- Mostrar antes de pedir.
- Um caminho principal por tela.
- A IA propõe e a pessoa confirma.
- Tudo reversível e visível ("o que aconteceu e por quê").

## 1. A jornada que queremos

| Momento | Hoje (antes da CAD-226) | Agora (CAD-226) | Próximo passo |
|---|---|---|---|
| **1º acesso** | Checklist "Primeiros passos" com links soltos | Abre sozinho o **"Fale sobre seu processo"**: temas + texto ou voz → a IA indica automações → "Criar e ver o fluxo" | Tour de 3 telas, vídeo de 60 s e convite para a equipe no mesmo passo |
| **Entender a automação** | Lista de regras com texto técnico | Botão **Abrir**: a regra vira um **fluxo desenhado** (Quando → Se → Faça), com as execuções atualizando sozinhas e cores por passo | Editar arrastando os blocos no próprio fluxo (unificar com "Fluxos com apps") |
| **Pedir à IA** | Chat em branco com sugestões genéricas | Atalho "Fale sobre seu processo" no Assistente; **escolher um documento** com atalhos "Extrair os dados", "Montar plano de ação", "Resumir", "Prazos e riscos" | Arrastar o arquivo para o chat; atalho "Usar no Assistente" em Publicações e Processos |
| **Falar com o cliente** | E-mail em texto puro, sem assinatura | **Visual do escritório** (moderno, clássico, simples) + **assinatura de cada pessoa** com imagem; prévia antes de ligar a regra | Modelos de mensagem por situação (audiência, cobrança, boas-vindas) prontos para escolher |
| **Fora do computador** | — | **Atalho no relógio, celular ou voz** dispara a regra | Notificações push no celular (PWA) com "aprovar envio" num toque |
| **Marketing** | Sugestão de arte em texto | **Imagem real** (IA ou arte da marca) com link público para o Instagram | Vídeo de slides gerado pelo Cadrius (ver `ESTUDO_VIDEO_E_RELOGIO.md`) |
| **Segurança no acesso** | Troca de senha temporária simples | Etapas, mostrar senha, força da senha, confirmação ao vivo, conta em uso visível | Entrar com passkey (Face ID ou digital) no lugar da senha |

## 2. Problemas de uso que ainda vemos e como atacar

| # | Problema | Onde | Proposta | Esforço |
|---|---|---|---|---|
| 1 | Dois tipos de automação ("Fluxos com apps" e "Regras do escritório") confundem | Automações | Uma lista só, "Automações", com etiqueta do tipo; o desenho do fluxo vale para os dois | M |
| 2 | Os números do topo de Automações contam só os "Fluxos com apps" (mostra 0 com regra ligada) | Automações | Somar as regras ligadas e as execuções do mês | P |
| 3 | O editor de regra mostra todos os campos de uma vez | Regras → Editar | Assistente em 3 passos (Quando, Se, Faça) com o fluxo ao lado mudando ao vivo | M |
| 4 | Sem "desfazer" depois de aceitar uma sugestão | Sugestões da IA | Toast com "Desfazer" (apaga a regra recém-criada, ainda desligada) | P |
| 5 | Muitos modais grandes no celular | Marketing, Regras | Viram telas inteiras (bottom sheet) abaixo de 600 px | M |
| 6 | Estados vazios sem próximo passo claro | Publicações, Processos, Contatos | Todo vazio com 1 botão principal + "peça ao Assistente" | P |
| 7 | Mensagens de erro técnicas em alguns formulários antigos | Cadastro, Integrações | Padronizar com `errorMessage` e dizer o que fazer | P |
| 8 | Busca Ctrl+K não acha ações | Topo | Incluir ações: "nova tarefa", "falar sobre meu processo", "gerar post" | P |

P = até 1 dia · M = 2 a 4 dias

## 3. Como medir

| Indicador | Meta para os primeiros 30 dias |
|---|---|
| Escritórios que concluem o "Fale sobre seu processo" | ≥ 60% dos novos |
| Tempo até ligar a 1ª automação | < 10 minutos do 1º login |
| Regras ligadas por escritório ativo | ≥ 3 |
| Pedidos ao Assistente por usuário na semana | ≥ 5 |
| Conteúdos de marketing publicados com imagem | ≥ 80% |

**Como coletar:** a auditoria já registra `automation.discovery`, `automation.suggestion_decided`,
`automation.rule_enabled`, `ai.request` e `marketing.image_generated`. Um painel na Gestão Cadrius (área Marketing)
pode somar isso por semana. Fica proposto para a próxima fase.

## 4. Ordem sugerida das próximas fases
1. **Fase N (UX rápida):** itens 2, 4, 6, 7 e 8. Uma semana; não mexe no modelo de dados.
2. **Fase O:** unificar as automações (item 1) e o editor em 3 passos (item 3), com o fluxo editável.
3. **Fase P:** celular, com PWA, push com aprovação num toque e bottom sheets (item 5).
4. **Fase Q:** vídeo de slides no Marketing e passkeys no login.

**Antes de cada fase:** rodar o roteiro de usabilidade (`docs/ROTEIRO_TESTE_USABILIDADE.md` do front) com 3 a 5 advogados key-users, medindo
tempo e erros nas tarefas dessa fase.
