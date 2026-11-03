"""Textos-base (v1.0) dos documentos legais e lista inicial de suboperadores.

ATENÇÃO: são rascunhos técnicos gerados para o projeto — marcados `needs_legal_review=True`.
Devem ser revisados por advogado/encarregado (DPO) antes de uso comercial. Para alterar o texto de
um documento já publicado, crie uma NOVA versão (o texto publicado é imutável).
"""

CIENCIA = """# Termo de Ciência de Tratamento de Dados

## 1. Papéis
O **Cadrius** atua como **operador** dos dados que o escritório (controlador) conecta à plataforma e como
**controlador** dos dados cadastrais de quem usa a plataforma (advogados e equipe).

## 2. Quais dados são utilizados
| Categoria | Exemplos | Origem |
|---|---|---|
| Identificação e contato do usuário | nome, e-mail, CPF, telefone, OAB/UF, área de atuação, foto | você |
| Dados do escritório | razão social, CNPJ, endereço, plano contratado | você |
| Credenciais de integração | senhas IMAP, tokens de API (guardados **cifrados**) | você |
| Conteúdo de comunicações | e-mails lidos via IMAP, mensagens WhatsApp, payloads de webhooks | sistemas conectados |
| Dados extraídos por IA | número de processo, prazos, partes, resumo | derivados do conteúdo |
| Registros técnicos e de segurança | IP, identificador do navegador (hash), data/hora, ações realizadas | uso da plataforma |
| Pagamento | identificador de cliente/assinatura (os dados de cartão ficam com o Stripe) | Stripe |

## 3. Finalidades e bases legais
- Prestar o serviço contratado e executar as automações configuradas (execução de contrato — art. 7º, V).
- Segurança, prevenção a fraudes e auditoria de acessos (legítimo interesse — art. 7º, IX — e obrigação legal).
- Cumprir obrigações legais e atender a direitos dos titulares (art. 7º, II).
- Comunicações opcionais de produto: **somente com consentimento**, que pode ser revogado a qualquer momento.

## 4. Compartilhamento e transferência internacional
Para prestar o serviço, trechos de conteúdo e metadados podem ser enviados a **suboperadores** (provedores de IA,
e-mail, mensageria, pagamentos, monitoramento e backup), alguns **fora do Brasil**. A lista atualizada, com país e
finalidade, está em **/api/v1/legal/subprocessors/** e na tela de Privacidade.

## 5. Inteligência Artificial
A IA lê o conteúdo para sugerir/extrair informações e gerar rascunhos de automações. **Não há decisão automatizada
exclusiva**: automações criadas por IA nascem como **rascunho** e só entram em operação após aprovação de um
Administrador/Dono do escritório.

## 6. Retenção
- Corpo de e-mails processados: 90 dias. Payloads/resultados de execuções: 90 dias. Logs de integração: 30 dias.
- Trilha de auditoria de segurança: 12 meses (online), sem conteúdo pessoal.
- Conta encerrada: dados do escritório mantidos 30 dias para recuperação e depois eliminados.

## 7. Segurança
Criptografia em trânsito e de credenciais em repouso, isolamento entre escritórios, controle de acesso por cargo,
trilha de auditoria imutável e detecção de comportamento anômalo.

## 8. Seus direitos
Confirmação, acesso, correção, anonimização/eliminação, portabilidade, informação sobre compartilhamento e
revogação do consentimento (LGPD, art. 18). Pedidos pela plataforma ou pelo canal do encarregado; resposta em até 15 dias.

## 9. Responsabilidade do escritório (controlador)
O escritório declara possuir **base legal** para tratar os dados de terceiros (clientes, partes, contrapartes) que
conectar ao Cadrius e responde por informá-los conforme a LGPD.
"""

TERMS = """# Termos de Uso

1. **Objeto.** O Cadrius é uma plataforma de hiperautomação com IA para escritórios de advocacia.
2. **Conta e acesso.** Você é responsável por manter suas credenciais em sigilo e pelas ações realizadas na sua conta.
3. **Uso aceitável.** É proibido usar a plataforma para fins ilícitos, tentar burlar limites/segurança, acessar dados de
   outro escritório ou sobrecarregar o serviço (sujeito a bloqueio e a registro na trilha de auditoria).
4. **Conteúdo e dados.** O escritório permanece titular/controlador do conteúdo que conecta e garante ter base legal para
   seu tratamento. O Cadrius o trata somente para prestar o serviço.
5. **IA.** Resultados de IA podem conter imprecisões e devem ser revisados por profissional habilitado antes de uso.
6. **Planos e pagamento.** Limites e valores seguem o plano contratado; cobrança processada pelo Stripe.
7. **Disponibilidade e suporte.** O serviço é prestado com esforço razoável de disponibilidade, sem garantia de operação ininterrupta.
8. **Encerramento.** Você pode encerrar a conta; os dados do escritório são mantidos por 30 dias e então eliminados.
9. **Alterações.** Mudanças relevantes geram nova versão e exigem novo aceite.
"""

PRIVACY = """# Política de Privacidade

Esta política explica como o Cadrius trata dados pessoais, em conformidade com a Lei nº 13.709/2018 (LGPD).

**Encarregado (DPO):** privacidade@cadrius.ia.br

## O que coletamos
Dados cadastrais (nome, e-mail, CPF, telefone, OAB), dados do escritório, credenciais de integração (cifradas),
conteúdo das comunicações conectadas e registros técnicos (IP, data/hora, ações). Detalhes e bases legais:
**Termo de Ciência de Tratamento de Dados**.

## Para que usamos
Prestar o serviço, garantir a segurança, cumprir obrigações legais e, com consentimento, enviar comunicações opcionais.

## Com quem compartilhamos
Suboperadores listados em /api/v1/legal/subprocessors/ (inclusive provedores no exterior, com salvaguardas contratuais).
Não vendemos dados pessoais.

## Por quanto tempo guardamos
Prazos de retenção no Termo de Ciência. Ao fim da finalidade, os dados são eliminados ou anonimizados.

## Seus direitos
Acesso, correção, anonimização/eliminação, portabilidade, informação sobre compartilhamento e revogação de consentimento.
Exerça pela tela de Privacidade ou escreva ao encarregado. Você também pode reclamar à ANPD.

## Cookies e armazenamento local
Usamos apenas o necessário para autenticação e funcionamento (sem cookies de publicidade).
"""

# Versão 2.0 (verificação do app OAuth no Google): pública em https://app.cadrius.ia.br/politica-de-privacidade, sem login,
# com a seção "Dados de usuários do Google" exigida pela Política de Dados do Usuário dos Serviços de API do Google.
PRIVACY_V2 = """# Política de Privacidade do Cadrius

Versão 2.0, vigente desde 3 de novembro de 2026. Vale para o site e o aplicativo **app.cadrius.ia.br** e para a API **api.cadrius.ia.br**.

Esta política explica quais dados pessoais o Cadrius trata, para quê, com quem compartilha, como protege, por quanto tempo guarda e como você pede a exclusão. Segue a Lei nº 13.709/2018 (LGPD) e, para os dados que vêm das contas Google, a Política de Dados do Usuário dos Serviços de API do Google.

**Contato do encarregado (DPO):** privacidade@cadrius.ia.br

## 1. Quem somos e qual é o nosso papel
- O **Cadrius** é uma plataforma de gestão jurídica com inteligência artificial para advogados e escritórios de advocacia.
- Somos **controlador** dos dados de quem usa a plataforma (advogados e equipe): cadastro, login, pagamento e registros de segurança.
- Somos **operador** dos dados que o escritório cadastra ou conecta (clientes, processos, documentos, mensagens). Quem decide sobre esses dados é o escritório, que é o controlador.

## 2. Quais dados coletamos
| Categoria | Exemplos | Origem |
|---|---|---|
| Cadastro do usuário | nome, e-mail, CPF, telefone, OAB/UF, foto | você |
| Dados do escritório | razão social, CNPJ, endereço, plano contratado | você |
| Login | senha (guardada só como hash), segundo fator (MFA), identificador da conta Google ou Microsoft | você e o provedor de login |
| Conteúdo do escritório | contatos, processos, documentos, tarefas, e-mails e mensagens das integrações que você ligar | você e os sistemas conectados |
| Dados de contas Google | detalhados na seção 3 | Google, com a sua autorização |
| Registros técnicos e de segurança | IP, navegador (hash), data e hora, ações realizadas | uso da plataforma |
| Pagamento | identificador de cliente e de assinatura (os dados do cartão ficam com o Stripe) | Stripe |

## 3. Dados de usuários do Google
Esta seção descreve como o Cadrius acessa, usa, armazena, compartilha, protege, guarda e apaga dados que vêm da sua conta Google. O acesso só acontece depois que **você** autoriza na tela de consentimento do Google, e cada permissão é pedida apenas quando o recurso correspondente é usado.

### 3.1 Dados acessados
| Recurso do Cadrius | Permissão pedida ao Google | Dados acessados |
|---|---|---|
| Entrar com Google | openid, email, profile | nome, e-mail e identificador da conta Google. Não acessamos a sua senha do Google. |
| Google Agenda | calendar.events | compromissos da sua agenda principal, do dia anterior até o limite que você escolher (60 dias por padrão, no máximo 180): título, descrição, local, início e fim. O Cadrius também cria e altera compromissos que você pedir (com convidados, se você informar). |
| Planilhas e documentos do Cadrius no Drive | drive.file | **somente** os arquivos que o próprio Cadrius criou no seu Drive (por exemplo, a planilha de honorários de uma automação). O restante do seu Drive não fica visível. |
| Importar carteira de clientes do Drive | drive.readonly (pedida só nessa tela) | os nomes das subpastas e dos arquivos **da pasta que você indicar** e o conteúdo dos arquivos que você marcar para importar. Não percorremos outras pastas. |

### 3.2 Como usamos os dados do Google
- **Entrar com Google:** criar e identificar a sua conta e fazer o login, sem senha nova.
- **Google Agenda:** mostrar os seus compromissos no Cadrius, sugerir que prazos e audiências virem tarefas, avisar antes de um compromisso e criar ou alterar compromissos quando você ou uma automação aprovada por você pedir.
- **Planilhas e documentos (drive.file):** gravar linhas nas planilhas e criar documentos que você pediu ao Cadrius.
- **Importação do Drive:** cada subpasta vira um cliente do escritório e os arquivos dela viram documentos desse cliente, depois que você confere e confirma a prévia.
- **Inteligência artificial:** só quando você usa um recurso de IA (por exemplo, perguntar ao Assistente sobre a sua agenda ou marcar "Ler os documentos com a IA" na importação). O trecho necessário é enviado a um provedor de IA contratado que **não usa os dados para treinar modelos**. O Cadrius bloqueia por programação qualquer provedor que possa treinar com os dados.
- **Nunca** usamos dados do Google para publicidade, para criar perfis de marketing, para vender a terceiros, para avaliar crédito ou para desenvolver, melhorar ou treinar modelos de inteligência artificial ou aprendizado de máquina generalizados.

### 3.3 Compartilhamento dos dados do Google
- **Não vendemos** dados do Google, nem os compartilhamos para publicidade.
- **Dentro do seu escritório:** os compromissos e documentos ficam visíveis para as pessoas do escritório conforme as permissões definidas pelo responsável.
- **Suboperadores necessários para o serviço:** hospedagem e banco de dados no Brasil, cópia de segurança cifrada e, só quando você usa um recurso de IA, o provedor de IA contratado (sem treino). Todos atuam sob contrato e apenas para prestar o serviço. A lista completa, com país e finalidade, está na seção 6.
- **Pessoas:** ninguém da equipe Cadrius lê os seus dados do Google, exceto com a sua autorização expressa (por exemplo, num chamado de suporte), quando for necessário para segurança (investigar abuso ou incidente) ou para cumprir a lei.
- **Obrigação legal:** quando exigido por lei ou ordem judicial, comunicando você sempre que a lei permitir.

### 3.4 Uso Limitado
O uso e a transferência, pelo Cadrius, de informações recebidas das APIs do Google para qualquer outro aplicativo seguirão a **Política de Dados do Usuário dos Serviços de API do Google** (https://developers.google.com/terms/api-services-user-data-policy), incluindo os requisitos de **Uso Limitado**.

### 3.5 Armazenamento e proteção
- A autorização do Google (token de atualização) fica **cifrada** no banco de dados. Não guardamos a sua senha do Google.
- Título, descrição e local dos compromissos e todo documento importado ficam **cifrados** no banco e no armazenamento de arquivos.
- O arquivo .zip de uma importação fica numa pasta privada do servidor e é apagado ao terminar.
- Toda conexão usa HTTPS (TLS). O acesso interno é limitado por cargo, com isolamento entre escritórios, segundo fator de autenticação e trilha de auditoria à prova de alteração.

### 3.6 Retenção e exclusão dos dados do Google
| Dado | Por quanto tempo fica |
|---|---|
| Autorização do Google (token) | até você desconectar o Google ou excluir a conta |
| Compromissos trazidos da Agenda | enquanto a conexão estiver ativa, e apagados 90 dias depois do fim de cada compromisso |
| Arquivos criados pelo Cadrius no seu Drive | ficam no **seu** Drive. No Cadrius guardamos só o nome e o link. |
| Documentos importados do Drive | viram documentos do escritório e seguem a retenção do escritório (até alguém excluir ou o escritório encerrar a conta) |
| .zip e prévia de importação | apagados ao terminar a importação. Prévias abandonadas são apagadas em até 48 horas. |

**Como pedir a exclusão:**
- **Desconectar o Google:** no Cadrius, em **Configurações → Integrações → Google → Desconectar**. Revogamos a autorização no Google na hora e apagamos os compromissos trazidos da sua agenda. Os eventos e arquivos que estão na sua conta Google continuam lá.
- **Revogar pelo Google:** a qualquer momento em https://myaccount.google.com/permissions
- **Excluir dados ou a conta:** no Cadrius, em **Segurança → Privacidade → Fazer um pedido** (eliminação), ou por e-mail para privacidade@cadrius.ia.br, **mesmo sem conseguir entrar na conta**. Respondemos em até 15 dias.
- **Ao encerrar a conta do escritório:** os dados ficam bloqueados por 30 dias (para recuperação ou exportação) e depois são eliminados de forma definitiva. As cópias de segurança cifradas são sobrescritas no ciclo normal de rotação.

## 4. Para que usamos os dados e com que base legal
- Prestar o serviço contratado e executar as automações configuradas (execução de contrato, art. 7º, V).
- Segurança, prevenção a fraudes e auditoria de acessos (legítimo interesse, art. 7º, IX, e obrigação legal).
- Cumprir obrigações legais e regulatórias (art. 7º, II).
- Comunicações opcionais sobre o produto: **somente com o seu consentimento**, que pode ser revogado a qualquer momento.

## 5. Inteligência artificial
- A IA lê o conteúdo para extrair informações, responder ao Assistente e sugerir automações.
- Não há decisão automatizada exclusiva: automações criadas pela IA ficam como rascunho até um responsável aprovar.
- O escritório pode desligar a IA, restringir provedores e definir o nível de autonomia.
- Dados de clientes e dados do Google só vão a provedores que **não treinam** modelos com o conteúdo.

## 6. Com quem compartilhamos
- **Suboperadores** (hospedagem, banco de dados, cópia de segurança, IA, e-mail, mensagens, pagamentos e monitoramento), alguns fora do Brasil, sempre com salvaguardas contratuais. A lista atualizada, com país e finalidade, aparece no fim desta página.
- **Não vendemos** dados pessoais.

## 7. Transferência internacional
Alguns suboperadores ficam fora do Brasil (por exemplo, nos Estados Unidos). Nesses casos, usamos cláusulas contratuais e enviamos apenas o necessário (art. 33 da LGPD).

## 8. Segurança
Criptografia em trânsito e em repouso, campos sensíveis cifrados, isolamento entre escritórios, controle de acesso por cargo, segundo fator de autenticação, trilha de auditoria à prova de alteração, detecção de comportamento anômalo e cópias de segurança diárias cifradas.

## 9. Por quanto tempo guardamos (geral)
- Corpo de e-mails processados: 90 dias. Dados de execuções de automações: 90 dias. Registros de integrações: 30 dias.
- Trilha de auditoria de segurança: 12 meses, sem conteúdo pessoal.
- Conta encerrada: 30 dias para recuperação e depois a eliminação.
- Dados de contas Google: ver a seção 3.6.

## 10. Seus direitos
Confirmação, acesso, correção, anonimização, bloqueio ou eliminação, portabilidade, informação sobre compartilhamento e revogação do consentimento (LGPD, art. 18). Peça pela tela **Privacidade** do Cadrius ou por e-mail ao encarregado (privacidade@cadrius.ia.br). Respondemos em até 15 dias. Você também pode reclamar à ANPD (https://www.gov.br/anpd).

## 11. Cookies e armazenamento local
Usamos apenas o necessário para o login e para o funcionamento (por exemplo, tema claro ou escuro). Não usamos cookies de publicidade nem rastreadores de terceiros.

## 12. Menores de idade
O Cadrius é destinado a profissionais. Não coletamos intencionalmente dados de menores de 18 anos como usuários da plataforma.

## 13. Alterações desta política
Mudanças relevantes geram uma nova versão, publicada nesta mesma página, e avisamos dentro da plataforma.

## Google user data (summary in English)
- **Data accessed:** Google Sign-In (name, email, Google account ID). Google Calendar (calendar.events: title, description, location, start and end of events in the primary calendar, from yesterday up to 60 days ahead by default, at most 180 days; it also creates or updates events the user asks for). Google Drive with drive.file (only files created by Cadrius). Google Drive with drive.readonly, requested only when the user imports a client portfolio (folder and file names inside the folder the user selects, and the content of the files the user chooses to import).
- **Data usage:** only to provide the user-facing features above: sign-in, showing and creating calendar events, writing to Cadrius-created spreadsheets and docs, and importing the selected folders as clients and documents. AI features run only on user request, through providers that do not train on the data. We never use Google user data for advertising, for sale, or to develop, improve or train generalized AI/ML models.
- **Data sharing:** we do not sell Google user data. It is shared only with the user's own law firm (by permission) and with service providers strictly needed to run the service (hosting in Brazil, encrypted backup and, on request, a non-training AI provider), or when required by law. No human at Cadrius reads it without the user's consent, except for security or legal reasons.
- **Storage and protection:** the OAuth refresh token, event text and imported documents are encrypted at rest. All traffic uses TLS. Access is role-based, with tenant isolation, MFA and a tamper-evident audit trail.
- **Retention and deletion:** tokens are kept until the user disconnects Google or deletes the account. Calendar copies are deleted on disconnect and 90 days after each event ends. Temporary import files are deleted when the import finishes (abandoned previews within 48 hours). Users can disconnect in Settings → Integrations → Google (which revokes the token at Google), revoke access at https://myaccount.google.com/permissions, or request deletion in the app or by email to privacidade@cadrius.ia.br, even without logging in. We reply within 15 days.
- **Limited Use:** Cadrius's use and transfer to any other app of information received from Google APIs will adhere to the Google API Services User Data Policy (https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.
"""

AI_NOTICE = """# Aviso sobre o uso de Inteligência Artificial

- Para extrair informações e sugerir automações, trechos do conteúdo (e-mails, documentos, mensagens) são enviados a
  provedores de IA (**OpenAI, Google Gemini ou Groq**, conforme o perfil de extração), que podem processar os dados **fora do Brasil**.
- O conteúdo enviado é limitado ao necessário; o Cadrius registra **quais provedores/categorias** foram usados (sem o conteúdo) na trilha de auditoria.
- A IA **não toma decisões jurídicas**: automações geradas por IA ficam como **rascunho** até a aprovação de um Administrador/Dono.
- O escritório pode desligar a IA, restringir provedores e definir o nível de autonomia nas configurações de governança.
- Respostas podem conter erros; revise antes de agir.
"""

DOCUMENTS = [
    ('terms', 'Termos de Uso', TERMS),
    ('privacy', 'Política de Privacidade', PRIVACY),
    ('ciencia', 'Termo de Ciência de Tratamento de Dados', CIENCIA),
    ('ai_notice', 'Aviso sobre Inteligência Artificial', AI_NOTICE),
]

SUBPROCESSORS = [
    ('OpenAI', 'Estados Unidos', 'Extração de dados e geração de automações por IA (GPT)', ['conteudo_comunicacao', 'processual']),
    ('Google (Gemini, Login, Sheets)', 'Estados Unidos', 'IA (Gemini), login social (OAuth) e integração com planilhas', ['conteudo_comunicacao', 'identificacao']),
    ('Groq', 'Estados Unidos', 'Inferência de IA (Llama) para extração e geração de automações', ['conteudo_comunicacao', 'processual']),
    ('Microsoft (login social)', 'Estados Unidos', 'Autenticação via conta Microsoft', ['identificacao']),
    ('Stripe', 'Estados Unidos / Irlanda', 'Processamento de pagamentos e assinaturas', ['identificacao', 'pagamento']),
    ('Supabase', 'Estados Unidos', 'Armazenamento de backups cifrados', ['backup_cifrado']),
    ('Sentry', 'Estados Unidos', 'Monitoramento de erros (sem dados pessoais automáticos)', ['registros_tecnicos']),
    ('Meta / WhatsApp (via Evolution API)', 'Estados Unidos', 'Envio e recebimento de mensagens WhatsApp', ['contato', 'conteudo_comunicacao']),
    ('Telegram', 'Reino Unido / EAU', 'Notificações opcionais', ['contato']),
    ('Trello / ClickUp', 'Estados Unidos', 'Criação de cartões/tarefas nas integrações do cliente', ['processual']),
    ('Locaweb (hospedagem)', 'Brasil', 'Hospedagem da aplicação e do banco de dados', ['todas']),
]
