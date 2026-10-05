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
    'WEBHOOK': {
        'label': 'Webhook customizado', 'categoria': 'Dados', 'uso': 'Receber eventos de qualquer sistema que envie webhooks.',
        'campos': [], 'guia': ['Crie a conexão e use a URL gerada no fluxo como destino no sistema de origem.'], 'links': [],
    },
}

CATEGORIES = ['Comunicação', 'Documentos', 'Financeiro', 'Marketing', 'Tarefas', 'ERP jurídico', 'Dados']


def public_catalog() -> list:
    return [{'app': key, **{k: v for k, v in spec.items()}} for key, spec in CATALOG.items()]


def missing_required(app: str, credentials: dict) -> list:
    spec = CATALOG.get(app) or {}
    return [f['label'] for f in spec.get('campos', []) if f.get('required') and not str((credentials or {}).get(f['key'], '')).strip()]


def is_yes(value) -> bool:
    return str(value or '').strip().lower() in ('sim', 's', 'yes', 'true', '1')
