# CAD-230: Google numa conexão só, agenda com escrita, automações com cálculo, painel e perfil

## 1. Google: Agenda, Planilhas e Documentos (e login)

### Como era

| Ponto | Situação |
|---|---|
| **Agenda** | Precisava de um app OAuth **por escritório**: criar projeto no Google Cloud, ativar a API, configurar a tela de consentimento, cadastrar o redirect e colar ID e segredo. Poucos escritórios conseguem fazer isso sozinhos. |
| **Escrita na agenda** | Só as **tarefas** com "sincronizar" iam para o Google. Compromissos do Google eram **só lidos**. O Assistente respondia "não consigo criar o evento no Google Agenda". |
| **Planilhas** | No catálogo havia um "token de acesso", que expira em 1 hora. Na prática não funcionava. |
| **Documentos** | Não havia integração. |
| **Login com Google (SSO)** | Já existe (`GOOGLE_CLIENT_ID/SECRET`), mas pede só `openid email profile`, separado da agenda. |

### Opções avaliadas

| Opção | Prós | Contras | Decisão |
|---|---|---|---|
| A. Manter um app por escritório | O Cadrius não passa por verificação no Google | O escritório quase nunca consegue configurar | Fica como **opção avançada** |
| B. **App OAuth do Cadrius** (um só para todos) | O escritório só clica em "Conectar Google" | Escopo `calendar.events` é **sensível**: o Google exige verificação do app (política de privacidade, vídeo de demonstração, domínio verificado; 2 a 6 semanas). Até lá, o app fica em "teste" (até 100 usuários de teste) ou mostra o aviso "app não verificado" | **Adotada** |
| C. Juntar no login (SSO) com escopos extras | Um clique a menos | Login viraria "pedir acesso à agenda" para todo mundo, inclusive quem não quer; mistura autenticação com autorização | Descartada |
| D. Escopos amplos (`drive`, `spreadsheets`) | Ler qualquer planilha da pessoa | Escopos **restritos**: exigem auditoria de segurança anual paga (CASA). Desproporcional | Descartada |

### O que foi implementado

**Conexão única "Conectar Google"**
- **Credenciais:** usa o app do Cadrius:
  - `GOOGLE_WORKSPACE_CLIENT_ID/SECRET`;
  - se estiverem vazios, o mesmo app do login (`GOOGLE_CLIENT_ID/SECRET`).
- **Segredo:** o segredo da plataforma nunca vai para o banco.
- **App próprio do escritório:** continua possível em "Avançado" e tem prioridade. Trocar de app pede reconexão.
- **Escopos:**
  - `openid email`: mostra "conectado como fulano@…";
  - `calendar.events`;
  - `drive.file`: o Cadrius só enxerga os arquivos que **ele mesmo cria**. É um escopo **não sensível** e é o recomendado pelo Google.
- **Conexões antigas:** quem conectou antes vê "Reconectar" para liberar Planilhas e Documentos. A agenda continua funcionando sem reconectar.

**Agenda: ler, criar, alterar e cancelar**
- **Na tela:** Integrações → Google → "Novo compromisso", além de "Alterar" e "Cancelar" em cada linha.
- **No Assistente:**
  - `criar_evento_google` e `alterar_evento_google`, sempre com confirmação;
  - `agenda_google` traz do Google o que mudou antes de responder e mostra o dia de hoje inteiro.
  - O caso do print ("crie Reunião hoje às 10h") agora vira um cartão "Criar no Google Agenda" para confirmar.
- **Convidados:** só recebem e-mail do Google quando a pessoa marca "mandar o convite".
- **Automação:** nova ação "Criar compromisso no Google Agenda".

**Planilhas e Documentos**
- **No Assistente:**
  - `exportar_para_planilha`: "exporte os honorários em aberto para uma planilha";
  - `criar_documento_google`: um texto ou uma minuta vira Google Docs.
- **Automação:** "Registrar em planilha do Google".
  - Na 1ª vez cria a planilha "Cadrius — X" com cabeçalho; depois só acrescenta linhas.
  - Se a pessoa apagou a planilha, ela é recriada.
- **Segurança dos valores:**
  - Valores vão como `RAW`: `=FÓRMULA` vinda de dado de terceiro fica como texto, não vira fórmula.
  - Valores como "1.500,00" viram número para dar para somar.
  - CPF, CNJ, telefone e códigos com zero à esquerda continuam texto.

### Para colocar em produção
1. **Criar o app no Google Cloud**, no projeto da Cadrius, ou reaproveitar o do login:
   - **APIs:** ative Google Calendar API, Google Sheets API e Google Docs API.
   - **Tela de consentimento:**
     - tipo Externo;
     - nome "Cadrius";
     - logo;
     - domínio `cadrius.ia.br`;
     - link da política de privacidade e dos termos;
     - escopos `openid`, `email`, `calendar.events` e `drive.file`.
   - **Credencial:** cliente OAuth do tipo "Aplicativo da Web", com estes redirecionamentos:
     - `https://api.cadrius.ia.br/api/v1/integrations/google-calendar/callback/`
     - `https://api-teste.cadrius.ia.br/api/v1/integrations/google-calendar/callback/`
     - mais os do login, que já existem.
2. **No `.env`:** `GOOGLE_WORKSPACE_CLIENT_ID` e `GOOGLE_WORKSPACE_CLIENT_SECRET`. Se ficarem vazios, vale o app do login.
3. **Enquanto o app não for verificado:** publique em "Teste" e adicione os e-mails dos escritórios piloto (até 100).
4. **Pedir a verificação do Google**, por causa de `calendar.events`, com:
   - vídeo mostrando o "Conectar Google";
   - criação de um compromisso e a planilha;
   - justificativa de cada escopo.

   O texto da justificativa está no item 1.3 abaixo.

#### 1.3 Justificativa dos escopos (para o formulário do Google)
- **`calendar.events`:** o advogado cria, altera e lê audiências, prazos e reuniões do próprio calendário pelo Cadrius (tela, assistente e automações). O Cadrius não acessa outros calendários nem configurações.
- **`drive.file`:** criar planilhas e documentos a pedido da pessoa (exportar listas, registrar dados das automações, salvar minutas) e acrescentar linhas nas planilhas que o próprio Cadrius criou. Não lê outros arquivos do Drive.

## 2. IA + automação: mais capacidade de processamento

### Onde estávamos
O motor de regras (gatilho → condições → ações) é robusto:
- simulação obrigatória;
- aprovação de envios;
- consentimento conferido de novo na hora de enviar;
- deduplicação;
- limite diário.

Mas as ações só **renderizavam variáveis do evento**. Não dava para:
- calcular, por exemplo multa e juros, honorário proporcional, dias de atraso ou percentual da meta;
- juntar dados, por exemplo "todos os honorários em aberto deste cliente" ou "prazos da semana";
- decidir um passo por um resultado, por exemplo "só cria tarefa se a multa passar de R$ 1.000".

### O que foi feito (sem mudar o que já funciona)
Todos os passos novos rodam no **planejamento**, então a **simulação mostra os números** antes de ligar a regra.

| Passo novo | O que faz | Exemplo |
|---|---|---|
| **Calcular** | Conta com as variáveis e funções em português: `arredondar`, `minimo`, `maximo`, `soma`, `media`, `abs`, `se`, `dias_entre`. Aceita `%` e vírgula decimal | `{{honorario.valor}} * 2% + {{honorario.valor}} * 0,033% * {{honorario.dias_atraso}}` → `{{calc.multa}}` = "R$ 34,95" |
| **Tabela temporária** | Lista vinda dos dados do escritório. Fontes: honorários em aberto ou vencidos, tarefas abertas, prazos da semana, processos parados, despesas do mês, oportunidades abertas. Pode filtrar pelo cliente do evento | `{{tabela.abertos.texto}}` (lista pronta para mensagem), `.total`, `.quantidade` |
| **Só fazer se…** (em qualquer passo) | Condição do passo, avaliada depois dos cálculos anteriores. Passo pulado não conta como falha | Criar tarefa só se `calc.multa_valor` for maior que 1000 |
| **Comparações numéricas** | `maior que`, `maior ou igual`, `menor que`, `menor ou igual`. Também nas condições da regra. Entende "R$ 1.234,56" | Honorário ≥ R$ 5.000 → avisar o sócio |
| **Registrar em planilha do Google** | Linha com colunas próprias ou a tabela inteira | Régua de cobrança alimenta a planilha "Cobranças" |
| **Criar compromisso no Google Agenda** | Data em dias úteis ou antes do prazo, com hora e duração | Publicação com audiência → compromisso no Google |

**Segurança do cálculo**
- Não usa `eval`. A conta passa por uma árvore sintática restrita.
- Só aceita números, variáveis, + − × ÷, potência pequena, comparações e as funções da lista.
- Não aceita atributos, listas, `lambda`, `import` nem nomes soltos. Os testes cobrem essas tentativas.
- Limite de 400 caracteres.

**A tabela é temporária de verdade**
- Existe só durante a execução.
- Não grava nada além do que os passos seguintes fizerem.
- Fica limitada a 200 linhas e ao escritório da regra.

**IA**
- O catálogo que o Assistente lê ganhou um bloco "processamento" (funções, fontes e variáveis) e uma dica de como encadear os passos.
- Assim, ao pedir "monte uma régua que calcule multa e juros e registre na planilha", a IA monta a regra com os passos na ordem certa. A regra nasce desligada, para simular.

### Próximos passos sugeridos
1. **Mais fontes de tabela:**
   - publicações não confirmadas;
   - contratos por cliente;
   - horas lançadas (quando houver timesheet).
2. **Laço "para cada linha"**, por exemplo um aviso por honorário vencido. Exige limite e aprovação em lote para não virar envio em massa.
3. **"Calcular" com IA**, para extrair um valor de um texto (publicação ou e-mail), com custo de créditos e revisão humana.

## 3. Painel
- **Causa:** os números vinham de contadores por pessoa (`UserMessageSendCount`), que o fluxo novo não incrementava:
  - documentos enviados;
  - Regras;
  - mensagens das automações.

  Por isso o painel ficava parado.
- **Números:** agora são contados nos dados do escritório (documentos, automações ativas, automações rodadas, mensagens enviadas). O contador antigo vale como piso.
- **Tarefas:** o painel mostra as de hoje e as **atrasadas** não feitas (até 30 dias), com destaque. Dá para concluir direto do painel.
- **Atualização:** o painel se atualiza sozinho a cada minuto e ao voltar para a aba.

## 4. Perfil: foto e capa
- **Causas da foto que sumia:**
  - o PATCH do perfil ignorava o arquivo, porque o campo não estava no serializer;
  - `/media` não é servido em produção.
- **Novo envio:** foto e capa vão por `POST /api/v1/auth/profile/imagem/<foto|capa>/`.
  - **Validação:** a imagem passa pelo Pillow. São aceitos JPEG, PNG ou WebP, até 5 MB.
  - **Tratamento:** a imagem é redimensionada (foto 512×512, capa 1600×480) e regravada sem EXIF, ou seja, sem a localização do celular.
- **Exibição:** por link assinado, que muda a cada troca. Sem cache velho e sem precisar servir `/media`.
- **Capa:** imagem própria ou fundo pronto (7 opções), mais uma frase curta (até 140 caracteres) sobre o escritório ou o que a pessoa gosta.
- **LGPD:** o pedido do titular apaga a capa e a frase junto com a foto.

## Validação
- **Back:** 255 testes nas apps tocadas, além dos novos:
  - `automations/tests_compute.py`;
  - `gcal/tests_cad230.py`;
  - `accounts/tests_profile_painel.py`.
- **Front:**
  - 170 testes, incluindo `faseO.test.js`;
  - lint sem erros;
  - build OK.
