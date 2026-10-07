# CAD-227: estudo de usabilidade do front e relógio/voz como diferencial

## Parte 1: auditoria de UX, tela por tela

### Como foi feita
- **Telas:** as 23 telas do escritório, entrando como dono, em **notebook (1366×768)** e **celular (390×844)**.
- **Capturas:** cada tela inteira, com a área rolável aberta até o fim.
- **Medições automáticas por tela:**
  - botões e quantos são de destaque;
  - cartões e avisos;
  - palavras na tela;
  - tamanhos de fonte diferentes;
  - texto menor que 12 px;
  - alvos de toque menores que 32 px no celular;
  - estouro horizontal;
  - posição do título;
  - erros de API e de JavaScript.
- **Abas:** cada aba de cada tela foi aberta para conferir que funciona.

### Resultado geral
- **Funcionalidade:** nenhuma resposta 5xx e nenhum erro de JavaScript em 46 aberturas de tela (23 × 2 tamanhos) e nas abas.
- **Alinhamento:** o título de todas as telas está no mesmo lugar (x=280, y=92 no notebook; x=16 no celular). Nada estoura
  na horizontal.
- **Poluição:** concentrada em poucas telas.

| Tela | Medição (antes) | Problema | O que foi feito |
|---|---|---|---|
| **Integrações** | 676 palavras, 30 botões (29 azuis iguais), 41 cartões, 3.947 px de altura | Tudo gritava ao mesmo tempo; o selo "novo" em quase todos os apps não informava nada | Os **conectados** ficam em cima. Os apps viram uma **lista compacta**, com **filtro por categoria** e busca. "Conectar" virou botão discreto e o selo "novo" saiu. Altura: 3.064 px, e com o filtro cabe numa tela. |
| **Meu perfil** | 7 blocos numa coluna, 24 botões (8 de destaque), 2.717 px | Duas "assinaturas" (a do e-mail e a do plano) confundiam; o plano aparecia duas vezes | **4 abas**: Meus dados · Senha e acesso · Assinatura de e-mail · Plano e créditos. A volta do pagamento abre direto em "Plano e créditos". |
| **Automações** | Os números do topo mostravam **0** com regra ligada; abria em "Fluxos com apps", vazio | O topo contava só os fluxos; o nome "Automação de fluxo de trabalho" era técnico | Os números somam regras e fluxos. O "tempo economizado" é estimado (3 min por passo feito) e aparece em "h/min". A tela abre em **Regras**, onde estão as automações da IA. O título agora é **"Automações"**. |
| **Finanças** | Datas ocupando a largura toda; valores quebrando ("R$" sozinho na linha) | Perda de espaço e leitura ruim dos números | Período compacto. Valores sem quebra, com tamanho que se ajusta à coluna (vale para todos os cartões de número do sistema). |
| **Marketing** | Aviso fixo da OAB de 2 linhas em toda visita | Texto que quem usa já conhece ocupando a tela | Virou uma linha **"O que a OAB permite"**, que abre quando a pessoa quer ler. |
| **Equipe (celular)** | Tabela cortada: cargo, créditos e ações fora da tela | Informação escondida | No celular, a tabela vira **cartões empilhados** com o rótulo de cada dado. |
| **Celular em geral** | Filtros e botões pequenos com 30 px (8 no Marketing, 5 no Perfil e na Equipe) | Toque difícil | Mínimo de **40 px** de altura no celular. |
| **IA do escritório** | O título não era um título (h1) | Leitor de tela e navegação por títulos | Corrigido. |

### Telas que estão boas
Painel, Publicações, Processos, Agenda forense, Documentos, Minutas, Contatos, Carteira, Plugins, Importar,
Privacidade, Auditoria, Suporte e Notificações:
- entre 45 e 220 palavras;
- até 9 botões, com 1 de destaque por tela;
- sem alertas.

### Ficam para a próxima rodada
1. **IA segura:** a lista de 8 provedores ocupa meia tela. Proposta: mostrar só os configurados e um "ver todos".
2. **Painel no celular:** os "Primeiros passos" empurram as tarefas do dia para baixo. Proposta: no celular, mostrar só
   o próximo passo.
3. **Unificar "Regras" e "Fluxos com apps"** numa lista só (está no `PLANO_UX_FLUXO_DE_USO.md`).

## Parte 2: relógio e voz como diferencial

### Por que isso é diferencial
O advogado passa boa parte do dia **longe do computador**: audiências, fórum, cartório, reuniões, deslocamento. Hoje,
nessas horas, o trabalho fica parado:
- **envio esperando aprovação:** o cliente fica sem o aviso;
- **lembrete que se perde:** "anoto depois" não acontece;
- **equipe sem saber:** ninguém sabe que a audiência acabou.

Os sistemas jurídicos do mercado têm app de celular, mas não têm **aprovação pelo relógio por voz**, nem **atalhos que
disparam o fluxo do escritório**.

### O que existe de tecnologia (realidade, sem app próprio)

| Caminho | O que dá para fazer | Limites | Usamos? |
|---|---|---|---|
| **Atalhos da Apple** (iPhone + Apple Watch + Siri) | Ditar, chamar um link (POST), falar a resposta; aparece no relógio | Configurar uma vez no iPhone | **Sim**: caminho principal |
| **HTTP Shortcuts** (Android) + bloco no **Wear OS** | Mesmo modelo, com bloco no relógio | App de terceiros (gratuito) | **Sim** |
| **Alexa / Google** via IFTTT ou Home Assistant | Frase falada → chama o link | Não lê a resposta de volta | **Sim**, para atalhos e lembretes |
| **ntfy** (notificação aberta, pode ser auto-hospedada) | Aviso no celular e no relógio, com botões que chamam um link | Botões completos no Android e Wear OS; no iPhone, toca-se no aviso | **Sim**, opcional |
| App próprio para watchOS / Wear OS | Experiência nativa | Meses de desenvolvimento, publicação nas lojas e manutenção | Só com demanda |
| Skill própria da Alexa | "Alexa, pergunte ao Cadrius…" | Certificação da Amazon, conta vinculada | Fase futura |

### O que foi implementado

**1. Aparelhos pessoais** (Dia a dia → **Relógio e voz**)
- **Cadastro:** cada pessoa cadastra os aparelhos (Apple Watch/Siri, Wear OS, Alexa, Google, botão/NFC). Cada um recebe
  uma **chave própria**, mostrada uma vez. O banco guarda só o hash.
- **Duas permissões por aparelho:**
  - **Aprovar envios:** só se o cargo da pessoa aprova;
  - **Avisos no relógio.**
- **Passo a passo na tela**, por tipo de aparelho.

**2. Comandos de voz**
O aparelho manda o que foi falado e recebe uma frase curta, que o relógio mostra ou fala.

| Dizer | Faz |
|---|---|
| "pendências" | Até 3 envios aguardando aprovação, cada um com um **código de 4 dígitos** |
| "aprovar 4821" / "recusar 4821" | Decide aquele envio. Funciona com os números ditados ("quatro oito dois um") |
| "agenda de hoje" | Tarefas de hoje e prazos dos próximos 2 dias |
| "lembrete ligar para a Maria amanhã" | Cria a tarefa (amanhã às 9h, ou hoje na próxima hora) |
| "cheguei ao fórum vara cível sala 3" | Roda a regra de **Atalho** que tem essa frase; o resto vira `{{atalho.texto}}` |
| "ajuda" | Lembra os comandos |

**3. Aprovação pelo relógio**
- **Código de 4 dígitos:** cada envio aguardando aprovação tem o seu, estável e derivado da chave secreta do servidor.
  Ele também aparece em Automações → Aprovações ("código no relógio").
- **Sem código, nada é aprovado:** "aprovar" sozinho pede o código. Ninguém aprova "o último" sem saber o que é.
- **Dados de cliente:** o relógio nunca mostra nome nem texto da mensagem, só "mensagem ao cliente da regra X".
- **Auditoria:** registra o aparelho, a decisão e a pessoa.

**4. Avisos no relógio com botões**
- **O aviso:** quando um envio passa a esperar aprovação, os aparelhos com avisos ligados (e permissão de aprovar)
  recebem pelo ntfy "Cadrius: aprovação pendente · código 4821", com os botões **Aprovar** e **Recusar**.
- **Os botões:** chamam um link assinado, que vale 24 h e só para aquele aparelho e aquele envio. Se o envio já foi
  decidido, o link não faz nada.
- **Tópico secreto:** cada aparelho tem o seu, aleatório, de 24 caracteres.

**5. Frases de voz nas regras**
- **Onde configurar:** no gatilho **Atalho**, o editor de regras tem "Frases de voz que disparam a regra".
- **Como dispara:** a mesma regra roda pelo link do atalho (CAD-226) ou pela frase falada em qualquer aparelho da pessoa.

**6. Teste na tela**
"Experimente um comando" mostra a resposta num relógio desenhado. As consultas rodam de verdade; aprovar e criar
lembrete só dizem o que fariam.

### Segurança e LGPD

| Risco | Proteção |
|---|---|
| Alguém descobre o link do aparelho | Chave de 256 bits; o banco guarda só o hash; "Remover" mata o link na hora; no máximo 20 comandos por minuto |
| A pessoa sai do escritório | O aparelho para de funcionar sozinho (exige vínculo ativo) |
| Aprovar o envio errado | Exige o código do envio; o relógio descreve a regra e o canal |
| Dados de cliente no relógio ou no serviço de avisos | O aviso e as respostas não têm nome nem texto de cliente |
| O serviço de avisos (ntfy) | Tópico secreto por aparelho; pode usar um ntfy próprio do Cadrius (`NTFY_BASE_URL`) |
| Rastreabilidade | Auditoria registra a criação, a remoção, cada comando (sem o texto falado) e cada decisão |

### Próximos passos possíveis (em ordem)
1. **ntfy próprio do Cadrius** no docker compose (um container leve): os avisos não passam por servidor de terceiros.
2. **Resumo da manhã no relógio** (8h): "3 tarefas, 1 prazo fatal, 2 envios para aprovar".
3. **Skill da Alexa e Ação do Google** oficiais, se clientes pedirem.
4. **App de relógio nativo**, só com demanda comprovada. O modelo de aparelhos e comandos já serve de base.

## Validação
- **Back:** testes novos em `automations/tests_voice.py`:
  - chave mostrada uma vez;
  - lembrete, agenda e ajuda;
  - aprovação por código, inclusive ditado;
  - recusa;
  - aparelho sem permissão;
  - frase disparando atalho;
  - remoção e saída do escritório;
  - teste na tela que não executa;
  - aviso com botões e decisão pelo link.
- **E2E:**
  - aparelho criado pela tela;
  - "pendências" listou 2 códigos, sem nome de cliente;
  - "aprovar" com o código ditado enviou a mensagem (status `success` no banco);
  - lembrete e agenda responderam;
  - o código apareceu em Aprovações;
  - telas revisadas conferidas no notebook e no celular.

## No servidor, depois do deploy
1. `migrate`: migração nova `automations 0007`.
2. `API_PUBLIC_URL` preenchido; ele é a base do link de voz.
3. Opcional: `NTFY_BASE_URL`. O padrão é `https://ntfy.sh`; para um ntfy próprio, aponte para ele.
4. Reinicie `web` e `worker`.
