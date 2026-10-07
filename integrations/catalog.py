"""Catálogo de integrações com guia "como pegar os dados" (CAD-174, fase E).

Critério de entrada (docs/PESQUISA_FASE_E.md): só apps que escritórios brasileiros usam no dia a dia E que têm API pública
utilizável por um escritório pequeno sem aprovação longa. Cada item diz para que o Cadrius usa o app, quais campos pedir, onde
o escritório encontra cada dado e o que ainda precisa ser validado. Os campos marcados ``secret`` nunca voltam para a tela.
"""
from __future__ import annotations

CATALOG = {
    'WHATSAPP': {
        'label': 'WhatsApp (Evolution API)', 'categoria': 'Comunicação',
        'uso': 'Mensagens das automações para clientes que autorizaram WhatsApp (sempre com aprovação por padrão).',
        'campos': [
            {'key': 'instance_name', 'label': 'Nome da instância', 'required': True},
            {'key': 'api_key', 'label': 'Chave da API', 'secret': True, 'required': True},
            {'key': 'base_url', 'label': 'URL do servidor Evolution', 'placeholder': 'https://wpp.seudominio.com'},
        ],
        'guia': [
            'Mais fácil: use o cartão "WhatsApp do escritório" no topo desta tela (sem servidor, só o número e o celular). '
            'Este formulário é para quem já tem uma Evolution API própria.',
            'No painel da sua Evolution API, abra "Instâncias" e copie o nome da instância conectada ao número do escritório.',
            'Em "Configurações" → "API Key", copie a chave (global ou da instância).',
            'Se a Evolution é hospedada por você, informe a URL pública dela (https://…). Sem URL, usamos o servidor do Cadrius.',
            'Teste: o botão "Testar conexão" consulta o estado da instância.',
        ],
        'links': [{'label': 'Documentação Evolution API', 'url': 'https://doc.evolution-api.com/'}],
    },
    'SMTP': {
        'label': 'E-mail do escritório (SMTP)', 'categoria': 'Comunicação', 'novo': True,
        'uso': 'Os e-mails das automações (boas-vindas, avisos) saem com o endereço do escritório, não do Cadrius.',
        'campos': [
            {'key': 'host', 'label': 'Servidor SMTP', 'required': True, 'placeholder': 'smtp.gmail.com'},
            {'key': 'port', 'label': 'Porta', 'required': True, 'placeholder': '587'},
            {'key': 'username', 'label': 'Usuário (e-mail)', 'required': True},
            {'key': 'password', 'label': 'Senha de app', 'secret': True, 'required': True},
            {'key': 'from_email', 'label': 'Remetente', 'placeholder': 'Silva Advocacia <contato@silva.adv.br>'},
        ],
        'guia': [
            'Gmail/Google Workspace: ative a verificação em 2 etapas e crie uma "Senha de app" em myaccount.google.com → Segurança → '
            'Senhas de app. Servidor smtp.gmail.com, porta 587.',
            'Microsoft 365/Outlook: servidor smtp.office365.com, porta 587; o administrador precisa permitir "SMTP autenticado" na caixa.',
            'Locaweb/Hostgator/KingHost: use os dados de SMTP do painel de e-mail do domínio (geralmente porta 587).',
            'Nunca use a senha principal da conta: crie uma senha só para o Cadrius e revogue quando quiser.',
        ],
        'links': [{'label': 'Senhas de app do Google', 'url': 'https://support.google.com/accounts/answer/185833'}],
    },
    'ZAPSIGN': {
        'label': 'ZapSign (assinatura eletrônica)', 'categoria': 'Documentos', 'novo': True,
        'uso': 'Enviar procurações, contratos de honorários e minutas em PDF para assinatura e acompanhar quem já assinou.',
        'campos': [
            {'key': 'api_token', 'label': 'Token da API', 'secret': True, 'required': True},
            {'key': 'sandbox', 'label': 'Ambiente de testes? (sim/não)', 'placeholder': 'não'},
        ],
        'guia': [
            'Entre no ZapSign com a conta do escritório → "Configurações" → "Integração" → "Token de acesso da API".',
            'Copie o token (para testes, use o token do ambiente sandbox e responda "sim" no campo de testes).',
            'O plano do ZapSign precisa incluir acesso à API.',
        ],
        'links': [{'label': 'Documentação da API ZapSign', 'url': 'https://docs.zapsign.com.br/'}],
        'validar': 'Conferir no sandbox o envio de PDF e o retorno dos links de assinatura antes de usar com clientes.',
    },
    'ASAAS': {
        'label': 'Asaas (boleto e Pix)', 'categoria': 'Financeiro', 'novo': True,
        'uso': 'Gerar cobranças de honorários (boleto/Pix) para um contato do quadro, direto do Cadrius.',
        'campos': [
            {'key': 'api_key', 'label': 'Chave da API', 'secret': True, 'required': True},
            {'key': 'sandbox', 'label': 'Ambiente de testes? (sim/não)', 'placeholder': 'não'},
        ],
        'guia': [
            'No Asaas: "Minha conta" → "Integrações" → "Gerar chave de API". A chave aparece uma vez só: copie e cole aqui.',
            'Para testar sem cobrar ninguém, crie uma conta em sandbox.asaas.com e use a chave de lá (responda "sim" em testes).',
            'O CPF/CNPJ do contato é obrigatório para emitir boleto.',
        ],
        'links': [{'label': 'Documentação Asaas', 'url': 'https://docs.asaas.com/'}],
    },
    'META': {
        'label': 'Facebook e Instagram (Meta)', 'categoria': 'Marketing', 'novo': True,
        'uso': 'Publicar ou agendar os conteúdos aprovados na área de Marketing na página do Facebook e no Instagram profissional.',
        'campos': [
            {'key': 'page_id', 'label': 'ID da página do Facebook', 'required': True},
            {'key': 'page_access_token', 'label': 'Token de acesso da página (longa duração)', 'secret': True, 'required': True},
            {'key': 'ig_user_id', 'label': 'ID da conta do Instagram profissional (opcional)'},
        ],
        'guia': [
            'O Instagram precisa ser conta profissional (Empresa ou Criador) ligada à página do Facebook do escritório.',
            'Em developers.facebook.com crie um app do tipo "Empresa" e adicione os produtos "Facebook Login" e "Instagram".',
            'No "Explorador da Graph API", gere um token de usuário com pages_manage_posts, pages_read_engagement, '
            'instagram_basic e instagram_content_publish; troque por um token de longa duração e consulte /me/accounts para '
            'obter o token da página e o ID da página.',
            'O ID do Instagram aparece em /{id-da-página}?fields=instagram_business_account.',
            'Para publicar em contas de terceiros o app precisa passar pela revisão da Meta; para a própria página do escritório, '
            'o modo de desenvolvimento com você como administrador é suficiente.',
        ],
        'links': [{'label': 'Publicação de conteúdo no Instagram', 'url': 'https://developers.facebook.com/docs/instagram-platform/content-publishing'},
                  {'label': 'Explorador da Graph API', 'url': 'https://developers.facebook.com/tools/explorer/'}],
        'validar': 'Limite do Instagram: até 100 publicações por API em 24 h; o Instagram exige imagem em URL pública.',
    },
    'D4SIGN': {
        'label': 'D4Sign (assinatura eletrônica)', 'categoria': 'Documentos', 'novo': True,
        'uso': 'Alternativa ao ZapSign: enviar contratos e procurações para assinatura com validade jurídica (MP 2.200-2/2001).',
        'campos': [
            {'key': 'token_api', 'label': 'tokenAPI', 'secret': True, 'required': True},
            {'key': 'crypt_key', 'label': 'cryptKey', 'secret': True, 'required': True},
            {'key': 'sandbox', 'label': 'Ambiente de testes? (sim/não)', 'placeholder': 'não'},
        ],
        'guia': ['No D4Sign: menu do usuário → "Dev / API" → gere o tokenAPI e a cryptKey.',
                 'Para testar sem custo, crie uma conta no ambiente sandbox e responda "sim" no campo de testes.'],
        'links': [{'label': 'Documentação da API D4Sign', 'url': 'https://docapi.d4sign.com.br/'}],
        'validar': 'Conferir no sandbox o envio de documento e o webhook de assinatura antes de usar com clientes.',
    },
    'CLICKSIGN': {
        'label': 'Clicksign (assinatura eletrônica)', 'categoria': 'Documentos', 'novo': True,
        'uso': 'Para escritórios que já assinam pela Clicksign: enviar documentos e acompanhar as assinaturas.',
        'campos': [
            {'key': 'access_token', 'label': 'Access token da API', 'secret': True, 'required': True},
            {'key': 'sandbox', 'label': 'Ambiente de testes? (sim/não)', 'placeholder': 'não'},
        ],
        'guia': ['Na Clicksign: "Configurações" → "API" → copie o access token (o plano precisa incluir API).',
                 'Use primeiro o ambiente sandbox (app.clicksign.com só em produção).'],
        'links': [{'label': 'Documentação da API Clicksign', 'url': 'https://developers.clicksign.com/'}],
        'validar': 'Sem teste automático ainda: valide no sandbox antes de usar com clientes.',
    },
    'ESCAVADOR': {
        'label': 'Escavador (dados processuais)', 'categoria': 'Pesquisa jurídica', 'novo': True,
        'uso': 'Complementar o DataJud: buscar processos por nome/CPF/CNPJ das partes e monitorar diários oficiais (API paga por crédito).',
        'campos': [{'key': 'token', 'label': 'Token da API', 'secret': True, 'required': True}],
        'guia': ['No Escavador: "API" → "Tokens de acesso" → crie um token para o Cadrius.',
                 'Cada consulta consome créditos da sua conta Escavador: acompanhe o saldo no painel deles.'],
        'links': [{'label': 'API do Escavador', 'url': 'https://api.escavador.com/'}],
        'validar': 'Consultas por nome de parte trazem dados pessoais: use só com finalidade definida (LGPD art. 7º/IX ou VI).',
    },
    'NOTION': {
        'label': 'Notion', 'categoria': 'Tarefas', 'novo': True,
        'uso': 'Para escritórios que organizam processos e base de conhecimento no Notion.',
        'campos': [{'key': 'token', 'label': 'Token da integração interna', 'secret': True, 'required': True},
                   {'key': 'database_id', 'label': 'ID do banco de dados (opcional)'}],
        'guia': ['Acesse notion.so/profile/integrations → "Nova integração" (interna) → copie o "Internal Integration Secret".',
                 'Na página/banco que o Cadrius vai usar: "…" → "Conexões" → adicione a integração criada.'],
        'links': [{'label': 'API do Notion', 'url': 'https://developers.notion.com/'}],
    },
    'PIPEDRIVE': {
        'label': 'Pipedrive (CRM)', 'categoria': 'Comercial', 'novo': True,
        'uso': 'Escritórios que fazem captação no Pipedrive: levar negócios ganhos para a Carteira do Cadrius.',
        'campos': [{'key': 'api_token', 'label': 'Token da API pessoal', 'secret': True, 'required': True}],
        'guia': ['No Pipedrive: avatar → "Preferências pessoais" → "API" → copie o token pessoal.'],
        'links': [{'label': 'API do Pipedrive', 'url': 'https://developers.pipedrive.com/docs/api/v1'}],
    },
    'CALENDLY': {
        'label': 'Calendly (agendamento de consultas)', 'categoria': 'Comercial', 'novo': True,
        'uso': 'Consultas agendadas pelo site viram contato + tarefa no Cadrius (via webhook).',
        'campos': [{'key': 'token', 'label': 'Personal access token', 'secret': True, 'required': True}],
        'guia': ['No Calendly: "Integrações e apps" → "API e webhooks" → "Gerar novo token".',
                 'Webhooks exigem plano pago do Calendly.'],
        'links': [{'label': 'API do Calendly', 'url': 'https://developer.calendly.com/'}],
    },
    'SLACK': {
        'label': 'Slack', 'categoria': 'Comunicação', 'novo': True,
        'uso': 'Avisos das automações no canal da equipe (ex.: "publicação nova com prazo em 5 dias").',
        'campos': [{'key': 'webhook_url', 'label': 'URL do Incoming Webhook', 'secret': True, 'required': True,
                    'placeholder': 'https://hooks.slack.com/services/…'}],
        'guia': ['Em api.slack.com/apps → "Create New App" → "Incoming Webhooks" → ative → "Add New Webhook to Workspace".',
                 'Escolha o canal da equipe e copie a URL gerada.'],
        'links': [{'label': 'Incoming Webhooks do Slack', 'url': 'https://api.slack.com/messaging/webhooks'}],
    },
    'TEAMS': {
        'label': 'Microsoft Teams', 'categoria': 'Comunicação', 'novo': True,
        'uso': 'Avisos das automações num canal do Teams (para escritórios no Microsoft 365).',
        'campos': [{'key': 'webhook_url', 'label': 'URL do webhook do canal', 'secret': True, 'required': True,
                    'placeholder': 'https://….webhook.office.com/… ou URL do fluxo do Workflows'}],
        'guia': ['No canal do Teams: "…" → "Workflows" → modelo "Postar em um canal quando uma solicitação de webhook for recebida".',
                 'Conclua o assistente e copie a URL gerada (as antigas URLs "webhook.office.com" também funcionam enquanto existirem).'],
        'links': [{'label': 'Webhooks no Teams', 'url': 'https://learn.microsoft.com/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook'}],
    },
    'TELEGRAM': {
        'label': 'Telegram', 'categoria': 'Comunicação',
        'uso': 'Avisos da equipe por bot (alternativa ao sino, para quem prefere receber no celular).',
        'campos': [
            {'key': 'telegram_bot_token', 'label': 'Token do bot', 'secret': True, 'required': True},
            {'key': 'telegram_chat_id', 'label': 'ID do chat', 'required': True},
        ],
        'guia': ['Converse com o @BotFather no Telegram, envie /newbot e copie o token.',
                 'Adicione o bot ao grupo da equipe, envie uma mensagem e abra api.telegram.org/bot<TOKEN>/getUpdates para ver o chat id.'],
        'links': [{'label': 'Bots do Telegram', 'url': 'https://core.telegram.org/bots/tutorial'}],
    },
    'TRELLO': {
        'label': 'Trello', 'categoria': 'Tarefas',
        'uso': 'Criar cartões a partir dos fluxos com apps (para escritórios que já organizam o trabalho no Trello).',
        'campos': [{'key': 'trello_api_key', 'label': 'API key', 'secret': True, 'required': True},
                   {'key': 'trello_api_token', 'label': 'Token', 'secret': True, 'required': True},
                   {'key': 'trello_list_id', 'label': 'ID da lista', 'required': True}],
        'guia': ['Acesse trello.com/power-ups/admin, crie um Power-Up e copie a API key.',
                 'Na mesma página clique em "Token" para autorizar e copie o token.',
                 'Abra o quadro, acrescente ".json" no fim da URL e procure o "id" da lista desejada.'],
        'links': [{'label': 'API do Trello', 'url': 'https://developer.atlassian.com/cloud/trello/guides/rest-api/api-introduction/'}],
    },
    'CLICKUP': {
        'label': 'ClickUp', 'categoria': 'Tarefas', 'uso': 'Criar tarefas a partir dos fluxos com apps.',
        'campos': [{'key': 'token', 'label': 'Token pessoal', 'secret': True, 'required': True}],
        'guia': ['No ClickUp: avatar → "Settings" → "Apps" → "API Token" → "Generate". Copie o token (começa com pk_).'],
        'links': [{'label': 'API do ClickUp', 'url': 'https://clickup.com/api/'}],
    },
    'SHEETS': {
        'label': 'Google Sheets', 'categoria': 'Dados', 'uso': 'Registrar dados das automações em planilhas.',
        'campos': [{'key': 'token', 'label': 'Token de acesso', 'secret': True, 'required': True}],
        'guia': ['Para importar dados para o Cadrius, prefira "Importar dados" (planilha exportada em CSV/XLSX): não precisa de token.',
                 'Para escrever em planilhas, gere um token OAuth com escopo spreadsheets no Google Cloud Console.'],
        'links': [{'label': 'API do Google Sheets', 'url': 'https://developers.google.com/sheets/api'}],
    },
    'ASTREA': {
        'label': 'Astrea', 'categoria': 'ERP jurídico',
        'uso': 'O Astrea não oferece API pública: traga os dados pela importação de planilha.',
        'campos': [{'key': 'token', 'label': 'Token (se o Astrea fornecer ao seu escritório)', 'secret': True}],
        'guia': ['No Astrea, exporte clientes e processos em planilha (Excel/CSV).',
                 'No Cadrius, use "Importar dados": as colunas são sugeridas automaticamente e você confere antes de gravar.'],
        'links': [],
    },
    # ---------------------------------------------------------------- CAD-223
    'JUDIT': {
        'label': 'Judit (consulta e monitoramento processual)', 'categoria': 'Pesquisa jurídica', 'novo': True,
        'uso': 'Consulta de processos por CPF/CNPJ/OAB e monitoramento com aviso por webhook, nos tribunais que o DataJud não cobre '
               'bem (inclui segredo de justiça quando o escritório tem credencial). Cobrança por volume.',
        'campos': [{'key': 'api_key', 'label': 'Chave da API (api-key)', 'secret': True, 'required': True}],
        'guia': ['Solicite acesso em judit.io (plano por volume) e gere a chave no painel.',
                 'Defina no contrato o escopo de uso: consultas por CPF trazem dados pessoais (finalidade e base legal da LGPD).'],
        'links': [{'label': 'Documentação Judit', 'url': 'https://docs.judit.io/'}],
        'validar': 'Sem teste automático: valide uma consulta no ambiente deles antes de ligar automações.',
    },
    'JUSBRASIL': {
        'label': 'Jusbrasil Soluções (monitoramento e due diligence)', 'categoria': 'Pesquisa jurídica', 'novo': True,
        'uso': 'Para escritórios com contrato Jusbrasil Soluções (antigo Digesto): monitoramento de processos e diários, '
               'e análise de risco de partes.',
        'campos': [{'key': 'token', 'label': 'Token da API', 'secret': True, 'required': True}],
        'guia': ['O token é fornecido pela Jusbrasil Soluções no contrato corporativo (não há cadastro self-service).'],
        'links': [{'label': 'Jusbrasil Soluções', 'url': 'https://www.jusbrasil.com.br/solucoes'}],
        'validar': 'Sem teste automático: confirme com o suporte deles o endpoint liberado para o seu contrato.',
    },
    'AUTENTIQUE': {
        'label': 'Autentique (assinatura eletrônica)', 'categoria': 'Documentos', 'novo': True,
        'uso': 'Assinatura de contratos e procurações com plano gratuito para poucos documentos por mês — boa opção para autônomos.',
        'campos': [{'key': 'token', 'label': 'Token da API', 'secret': True, 'required': True}],
        'guia': ['No Autentique: "Configurações" → "API" → gere o token.', 'A API é GraphQL (https://api.autentique.com.br/v2/graphql).'],
        'links': [{'label': 'Documentação Autentique', 'url': 'https://docs.autentique.com.br/api'}],
        'validar': 'Teste a conexão e envie um documento de teste para você mesmo antes de usar com clientes.',
    },
    'NFEIO': {
        'label': 'NFE.io (nota fiscal de serviço)', 'categoria': 'Fiscal', 'novo': True,
        'uso': 'Emissão de NFS-e dos honorários para escritórios que não usam o Asaas, em centenas de prefeituras e no padrão nacional.',
        'campos': [{'key': 'api_key', 'label': 'Chave da API', 'secret': True, 'required': True},
                   {'key': 'company_id', 'label': 'ID da empresa na NFE.io', 'required': True}],
        'guia': ['Em app.nfe.io: "Conta" → "Chaves de acesso" → copie a chave de API.',
                 'Cadastre a empresa (CNPJ do escritório, certificado A1 e inscrição municipal) e copie o ID dela.'],
        'links': [{'label': 'API da NFE.io', 'url': 'https://nfe.io/docs/'}],
        'validar': 'Faça a primeira emissão em homologação; a emissão automática pelo Cadrius com NFE.io está em planejamento '
                   '(hoje a emissão automática é pelo Asaas).',
    },
    'OMIE': {
        'label': 'Omie (ERP financeiro)', 'categoria': 'Financeiro', 'novo': True,
        'uso': 'Escritórios que fazem o financeiro no Omie: levar clientes e contas a receber do Cadrius para o ERP.',
        'campos': [{'key': 'app_key', 'label': 'App Key', 'required': True}, {'key': 'app_secret', 'label': 'App Secret', 'secret': True, 'required': True}],
        'guia': ['No Omie: "Configurações" → "Integrações" → "Desenvolvedor" → crie um aplicativo e copie App Key e App Secret.'],
        'links': [{'label': 'Portal do desenvolvedor Omie', 'url': 'https://developer.omie.com.br/'}],
        'validar': 'Teste a conexão; use o conector de ERP (Gestão → ERP) para mapear quais dados vão para o Omie.',
    },
    'BREVO': {
        'label': 'Brevo (e-mail e newsletter)', 'categoria': 'Marketing', 'novo': True,
        'uso': 'Newsletter informativa do escritório e e-mails transacionais com melhor entrega que o SMTP comum.',
        'campos': [{'key': 'api_key', 'label': 'Chave da API (v3)', 'secret': True, 'required': True}],
        'guia': ['No Brevo: menu do usuário → "SMTP & API" → "Chaves de API" → "Gerar nova chave".',
                 'Newsletter só para quem consentiu (o Cadrius envia só contatos com e-mail autorizado).'],
        'links': [{'label': 'API do Brevo', 'url': 'https://developers.brevo.com/'}],
    },
    'MAILCHIMP': {
        'label': 'Mailchimp (newsletter)', 'categoria': 'Marketing', 'novo': True,
        'uso': 'Escritórios que já mantêm a newsletter no Mailchimp: sincronizar contatos que autorizaram e-mail.',
        'campos': [{'key': 'api_key', 'label': 'Chave da API (termina em -usNN)', 'secret': True, 'required': True},
                   {'key': 'list_id', 'label': 'ID da audiência (opcional)'}],
        'guia': ['No Mailchimp: "Profile" → "Extras" → "API keys" → "Create A Key".'],
        'links': [{'label': 'API do Mailchimp', 'url': 'https://mailchimp.com/developer/marketing/api/'}],
    },
    'RDSTATION': {
        'label': 'RD Station Marketing', 'categoria': 'Marketing', 'novo': True,
        'uso': 'Enviar os contatos do formulário de captação como conversão no RD Station (nutrição informativa, sem captação '
               'mercantil — Provimento OAB 205/2021).',
        'campos': [{'key': 'api_key', 'label': 'Token público (conversões)', 'secret': True, 'required': True}],
        'guia': ['No RD Station Marketing: "Perfil" → "Integrações" → "Tokens" → copie o token público.'],
        'links': [{'label': 'API do RD Station', 'url': 'https://developers.rdstation.com/'}],
        'validar': 'Sem teste automático (a API de conversões só grava). Envie um contato de teste e confira no RD.',
    },
    'ZOOM': {
        'label': 'Zoom (reuniões e audiências)', 'categoria': 'Comunicação', 'novo': True,
        'uso': 'Criar o link da reunião com o cliente ao marcar "Reunião" no funil e guardar o link na tarefa.',
        'campos': [{'key': 'account_id', 'label': 'Account ID', 'required': True},
                   {'key': 'client_id', 'label': 'Client ID', 'required': True},
                   {'key': 'client_secret', 'label': 'Client Secret', 'secret': True, 'required': True}],
        'guia': ['Em marketplace.zoom.us: "Develop" → "Build App" → "Server-to-Server OAuth".',
                 'Dê os escopos de reunião (meeting:write) e usuário (user:read) e ative o app.'],
        'links': [{'label': 'API do Zoom', 'url': 'https://developers.zoom.us/docs/api/'}],
    },
    'ZENVIA': {
        'label': 'Zenvia (SMS e WhatsApp oficial)', 'categoria': 'Comunicação', 'novo': True,
        'uso': 'Alternativa ao Evolution: WhatsApp pela API oficial da Meta e SMS para clientes sem WhatsApp.',
        'campos': [{'key': 'token', 'label': 'Token da API (X-API-TOKEN)', 'secret': True, 'required': True},
                   {'key': 'from', 'label': 'Remetente (número ou nome do canal)', 'required': True}],
        'guia': ['Na Zenvia: "Configurações" → "Tokens e webhooks" → crie um token.',
                 'O WhatsApp oficial exige modelos de mensagem aprovados pela Meta.'],
        'links': [{'label': 'API da Zenvia', 'url': 'https://zenvia.github.io/zenvia-openapi-spec/'}],
        'validar': 'Sem teste automático: envie um SMS de teste para o seu número.',
    },
    'BRASILAPI': {
        'label': 'BrasilAPI (CNPJ e CEP — já ativo)', 'categoria': 'Dados', 'novo': True,
        'uso': 'Já vem ligado: ao cadastrar uma empresa, o Cadrius busca razão social, situação e endereço na Receita Federal pelo CNPJ.',
        'campos': [], 'nativo': True,
        'guia': ['Não precisa conectar nada. Em Contatos, digite o CNPJ e use "Buscar na Receita".'],
        'links': [{'label': 'BrasilAPI', 'url': 'https://brasilapi.com.br/'}],
    },
    'WEBHOOK': {
        'label': 'Webhook customizado', 'categoria': 'Dados', 'uso': 'Receber eventos de qualquer sistema que envie webhooks.',
        'campos': [], 'guia': ['Crie a conexão e use a URL gerada no fluxo como destino no sistema de origem.'], 'links': [],
    },
}

CATEGORIES = ['Comunicação', 'Documentos', 'Financeiro', 'Fiscal', 'Comercial', 'Pesquisa jurídica', 'Marketing', 'Tarefas', 'ERP jurídico',
              'Dados']


def public_catalog() -> list:
    return [{'app': key, **{k: v for k, v in spec.items()}} for key, spec in CATALOG.items()]


def missing_required(app: str, credentials: dict) -> list:
    spec = CATALOG.get(app) or {}
    return [f['label'] for f in spec.get('campos', []) if f.get('required') and not str((credentials or {}).get(f['key'], '')).strip()]


def is_yes(value) -> bool:
    return str(value or '').strip().lower() in ('sim', 's', 'yes', 'true', '1')
