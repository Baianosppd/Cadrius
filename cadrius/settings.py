import os
from pathlib import Path
import environ
from django.core.exceptions import ImproperlyConfigured
from datetime import timedelta
import sentry_sdk 
from sentry_sdk.integrations.django import DjangoIntegration

# --- 1. INICIALIZAÇÃO DO AMBIENTE ---
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    CORS_ALLOWED_ORIGINS=(
        list,
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
    ),
    IMAP_PORT=(int, 993),
    # Corpo máx. (JSON / multipart) alinhado com Traefik buffering (~2MB); evita payloads enormes.
    DATA_UPLOAD_MAX_MEMORY_BYTES=(int, 2 * 1024 * 1024),
)

environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Ambiente lógico: development | staging | production (também vira tag/ambiente no Sentry).
DJANGO_ENV = env('DJANGO_ENV', default='development')

# --- 2. MONITORAMENTO (SENTRY) ---
SENTRY_DSN = env('SENTRY_DSN', default=None)
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        # Permite filtrar alertas por tag (ex.: environment:production) e ligar erros ao deploy.
        environment=env('DJANGO_ENV', default='development'),
        release=env('APP_VERSION', default='1.0.0'),
        integrations=[DjangoIntegration()],
        # Amostragem de performance configurável (100% em produção custa caro e expõe mais dados).
        traces_sample_rate=env.float('SENTRY_TRACES_SAMPLE_RATE', default=0.1),
        # LGPD: não enviar IP/cookies/e-mail automaticamente a um terceiro (suboperador).
        # O contexto de utilizador/escritório é enviado só como IDs (cadrius.sentry_context).
        send_default_pii=False,
        # Corpos de requisição podem conter dados pessoais (e-mails, payloads de webhook).
        max_request_body_size='never',
    )

# --- 3. CORE SETTINGS E SEGURANÇA BÁSICA ---
APP_VERSION = env('APP_VERSION', default='1.0.0')
_INSECURE_SECRET_KEY = 'django-insecure-change-me-in-prod'
DEBUG = env('DEBUG')
# Aceita SECRET_KEY ou DJANGO_SECRET_KEY (o deploy.yml gera DJANGO_SECRET_KEY). Sem isto, o
# fallback público assinaria os JWT e qualquer pessoa conseguiria forjar tokens.
SECRET_KEY = (
    env('SECRET_KEY', default=None)
    or env('DJANGO_SECRET_KEY', default=None)
    or _INSECURE_SECRET_KEY
)
if not DEBUG and SECRET_KEY == _INSECURE_SECRET_KEY:
    raise ImproperlyConfigured(
        'SECRET_KEY/DJANGO_SECRET_KEY não definida: recusando arrancar em produção '
        'com a chave padrão (permite forjar tokens JWT e sessões).'
    )
DATA_UPLOAD_MAX_MEMORY_SIZE = env('DATA_UPLOAD_MAX_MEMORY_BYTES')
FILE_UPLOAD_MAX_MEMORY_SIZE = env('DATA_UPLOAD_MAX_MEMORY_BYTES')
# Antes: lista fixa que ignorava a variável de ambiente ALLOWED_HOSTS definida no deploy.
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[
    'localhost', '127.0.0.1', '.ngrok-free.app', '.ngrok.io',
    'nonvinous-debbie-unrelated.ngrok-free.dev', 'cadrius.local',
])

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[
    'http://localhost',
    'http://127.0.0.1',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'https://*.ngrok-free.app',
    'https://*.ngrok.io',
    'https://nonvinous-debbie-unrelated.ngrok-free.dev',
])


SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Endurecimento de transporte/cookies (só em produção, para não quebrar o dev em http).
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=2592000)  # 30 dias
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    # Redirecionamento só quando o proxy garante X-Forwarded-Proto (evita loop em http interno).
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
    SECURE_REDIRECT_EXEMPT = [r'^healthz/$']
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

ENCRYPTION_KEY = env('ENCRYPTION_KEY', default=None)
# Só em DEBUG (dev/testes) é permitido derivar a chave da SECRET_KEY (ver core.utils).
ENCRYPTION_ALLOW_DERIVED_KEY = DEBUG
if not DEBUG and not ENCRYPTION_KEY:
    raise ImproperlyConfigured('ENCRYPTION_KEY não definida: credenciais de terceiros ficariam sem cifra.')
# Chave dos índices de busca dos dados pessoais cifrados (CAD-152). SEPARADA da ENCRYPTION_KEY. Perdê-la não perde dados
# (dá para reindexar com `manage.py encrypt_pii`), mas trocá-la sem reindexar quebra a busca por CPF/CNPJ/nome.
BLIND_INDEX_KEY = env('BLIND_INDEX_KEY', default='')
if not DEBUG and not BLIND_INDEX_KEY:
    raise ImproperlyConfigured('BLIND_INDEX_KEY não definida (índices de busca dos dados pessoais cifrados).')

# --- 4. APLICAÇÕES E MIDDLEWARES ---
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # logout/revogação de refresh tokens
    #'drf_yasg',
    'django_q',
    'axes',
    'drf_spectacular',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'allauth.socialaccount.providers.microsoft',

    # Local apps (O Core do Cadrius)
    'core',
    'accounts',
    'emails',
    'integrations', 
    'extraction', # Módulo de Extração de Dados (NLP, OCR, etc)
    'gcal',  # Google Calendar por escritório (CAD-162)
    'research',  # monitoramento de processos (DataJud) e notícias (CAD-166)
    'erp',  # conector declarativo de ERP jurídico (CAD-167)
    'backoffice',  # Gestão Cadrius: TI e Financeiro (CAD-168)
    'contacts',  # quadro de contatos (CAD-171)
    'imports',  # importação de planilhas (CAD-171)
    'support',  # suporte com a equipe Cadrius (CAD-171)
    'forense',  # calendário forense e prazos em dias úteis (CAD-172)
    'automations',  # regras de automação internas do escritório (CAD-172)
    'publications',  # caixa de publicações do DJEN com triagem (CAD-173)
    'minutas',  # minutas (rascunhos) sobre documentos e publicações (CAD-173)
    'marketing',  # conteúdo, calendário e campanhas — escritório e Cadrius (CAD-174)
    'carteira',  # funil, contratos de honorários e financeiro do escritório (CAD-175)
    'portal',  # portal do cliente por link seguro (CAD-175)
    'assistant',  # assistente de IA com conversa, ferramentas e ações confirmadas (CAD-221)
    'brain',  # Motor Cadrius: memória, aprendizado, regras e autonomia (CAD-165)
    'tasks', # Módulo de Tarefas Agendadas e Background Jobs
    'workflows',  #  Motor de Automação
    'webhooks',  # Recebedor de Eventos Externos
    'billing',# Módulo de Assinaturas e Pagamentos
    'audit',  # Trilha de auditoria imutável + anomalias (LGPD/ISO 27001)
    'privacy',  # Termos, consentimento versionado, DSR e retenção (LGPD)
    'aigov',  # Governança de IA: políticas, kill switch, humano no circuito
    'compliance',  # Centro de Segurança: ISO 27001/27701, LGPD, RoPA
    'documents',  # Documentos do escritório (ficheiros + metadados)
    'notifications',  # Sino de notificações
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',              
    'django.middleware.security.SecurityMiddleware',
    'audit.ipblock.BlockedIPMiddleware',                  # IPs bloqueados pela TI (CAD-221)
    'csp.middleware.CSPMiddleware',                       
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    
    # Middleware de Multi-tenancy 
    'cadrius.middleware.TenantMiddleware',
    # request_id/IP/ator para a trilha de auditoria (após autenticação e tenant)
    'audit.middleware.AuditContextMiddleware',
    
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'axes.middleware.AxesMiddleware',
]

ROOT_URLCONF = 'cadrius.urls'
WSGI_APPLICATION = 'cadrius.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


EVOLUTION_API_BASE_URL = env('EVOLUTION_API_BASE_URL', default='http://evolution-api:8080')
_DEFAULT_EVOLUTION_KEY = 'cadrius_mestre_secreto_123'
# O deploy.yml gera EVOLUTION_API_KEY; aceitamos os dois nomes.
EVOLUTION_API_GLOBAL_KEY = (
    env('EVOLUTION_API_GLOBAL_KEY', default=None)
    or env('EVOLUTION_API_KEY', default=None)
    or _DEFAULT_EVOLUTION_KEY
)
if not DEBUG and EVOLUTION_API_GLOBAL_KEY == _DEFAULT_EVOLUTION_KEY:
    raise ImproperlyConfigured(
        'EVOLUTION_API_GLOBAL_KEY/EVOLUTION_API_KEY não definida: a chave padrão é pública '
        'e dá controlo total sobre as instâncias de WhatsApp.'
    )

# --- 5. BANCO DE DADOS E AUTENTICAÇÃO ---
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR}/db.sqlite3')
}

AUTH_USER_MODEL = 'accounts.CustomUser'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesBackend', 
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# Configurações do Django Allauth para SSO e Social Login
# Configurações do Django Allauth para SSO e Social Login
SITE_ID = 1
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.B2BSocialAccountAdapter'
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'none'

AUTH_PASSWORD_VALIDATORS = [
    { 'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator', },
]

# Configurações do Axes (Segurança de Login)
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1 
AXES_LOCKOUT_TEMPLATE = None 
AXES_ENABLE_ACCESS_LOG = True
# Bloqueia por IP *ou* por utilizador: força bruta distribuída contra uma conta também é travada.
AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']
AXES_RESET_ON_SUCCESS = True
# Atrás do Traefik o REMOTE_ADDR é o do proxy: sem isto um atacante bloquearia TODOS os utilizadores.
AXES_IPWARE_PROXY_COUNT = env.int('AXES_PROXY_COUNT', default=1)
AXES_IPWARE_META_PRECEDENCE_ORDER = ('HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR')


# --- 6. INTERNACIONALIZAÇÃO E ARQUIVOS ---
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
DOCUMENT_PIPELINE_ENABLED = env.bool('DOCUMENT_PIPELINE_ENABLED', default=True)   # leitura automática após o upload (CAD-163)
CLAMAV_HOST = env('CLAMAV_HOST', default='')            # antivírus opcional (clamd); vazio = etapa pulada e registrada
CLAMAV_PORT = env.int('CLAMAV_PORT', default=3310)
OCR_LANGS = env('OCR_LANGS', default='por+eng')
DOCUMENT_MAX_BYTES = env.int('DOCUMENT_MAX_BYTES', default=25 * 1024 * 1024)   # teto por arquivo (a cifra é em memória)
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# --- 7. API, JWT E CORS ---
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'cadrius.authentication.SentryJWTAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Regista 403 (permission.denied) e 429 (ratelimit.hit) na trilha de auditoria.
    'EXCEPTION_HANDLER': 'audit.exception_handler.audit_exception_handler',
    # Throttling por scope (ScopedRateThrottle / SimpleRateThrottle com ``scope``).
    'DEFAULT_THROTTLE_RATES': {
        'webhook': '200/min',
        'webhook_catch': '60/min',
        # Endpoints de autenticação públicos (por IP): mitiga credential stuffing / abuso de cadastro.
        'auth_login': '10/min',
        'auth_register': '5/hour',
        'auth_refresh': '30/min',
        'auth_password_reset': '10/hour',
        'auth_mfa': '20/min',   # códigos de verificação em duas etapas (CAD-169)
    },
}

# --- Verificação em duas etapas (CAD-169): equipe Cadrius sempre; donos/admins de escritório quando ligado ---
MFA_REQUIRED_FOR_MANAGERS = env.bool('MFA_REQUIRED_FOR_MANAGERS', default=False)

# Suporte (CAD-171): e-mail da equipe avisado a cada chamado novo (só o aviso; o conteúdo fica cifrado no sistema)
SUPPORT_NOTIFY_EMAIL = env('SUPPORT_NOTIFY_EMAIL', default='')

# --- Assinatura / trial (CAD-119) — ver docs/ANALISE_PRECOS_PLANOS.md §6 ---
TRIAL_DAYS = env.int('TRIAL_DAYS', default=14)
TRIAL_CREDITS = env.int('TRIAL_CREDITS', default=30)       # créditos de IA durante o trial (independe do plano escolhido)
TRIAL_MAX_USERS = env.int('TRIAL_MAX_USERS', default=3)
GRACE_DAYS = env.int('GRACE_DAYS', default=7)              # cobrança falhou: tudo funciona até aqui
RESTRICTED_DAYS = env.int('RESTRICTED_DAYS', default=14)   # depois: IA pausada (leitura/exportação liberadas)
SUSPENDED_DAYS = env.int('SUSPENDED_DAYS', default=30)     # depois: suspensa; > 30 dias: cancelada
CREDIT_PACK_VALIDITY_DAYS = 365

# --- SSO (CAD-105): Google e Microsoft. Client id/secret vazios = login social desligado ---
GOOGLE_CLIENT_ID = env('GOOGLE_CLIENT_ID', default='')
GOOGLE_CLIENT_SECRET = env('GOOGLE_CLIENT_SECRET', default='')
MICROSOFT_CLIENT_ID = env('MICROSOFT_CLIENT_ID', default='')
MICROSOFT_CLIENT_SECRET = env('MICROSOFT_CLIENT_SECRET', default='')
MICROSOFT_TENANT = env('MICROSOFT_TENANT', default='common')
API_PUBLIC_URL = env('API_PUBLIC_URL', default='')  # ex.: https://api.cadrius.ia.br (base do redirect_uri do OAuth)

# --- E-mail transacional (recuperação de senha, convites, avisos). CAD-115/CAD-155 ---
# Sem EMAIL_HOST: em DEBUG imprime no console; em produção NÃO envia (backend 'dummy') para o link nunca ir parar nos logs.
# Provedor por preset (gmail | brevo | ses | locaweb | custom): troca futura = mudar EMAIL_PROVIDER + credenciais no .env.
from cadrius.email_presets import resolve as _email_preset  # noqa: E402
EMAIL_PROVIDER = env('EMAIL_PROVIDER', default='')
_preset = _email_preset(EMAIL_PROVIDER)
EMAIL_HOST = env('EMAIL_HOST', default=_preset['host'])
EMAIL_PORT = env.int('EMAIL_PORT', default=_preset['port'])
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=_preset['tls'])
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Cadrius <no-reply@cadrius.ia.br>')
EMAIL_BACKEND = env('EMAIL_BACKEND', default=(
    'django.core.mail.backends.smtp.EmailBackend' if EMAIL_HOST
    else 'django.core.mail.backends.console.EmailBackend' if DEBUG
    else 'django.core.mail.backends.dummy.EmailBackend'
))
PASSWORD_RESET_TIMEOUT = 60 * 60  # validade do link de recuperação (segundos)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    # Registra o último acesso no login por senha (Gestão Cadrius: "último acesso", usuários ativos 24 h/30 dias)
    'UPDATE_LAST_LOGIN': True,
}

SWAGGER_SETTINGS = {
    'SECURITY_DEFINITIONS': {
        'Bearer': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header'
        }
    },
    'USE_SESSION_AUTH': False,
}

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS')

# django-csp >= 4 ignora os antigos CSP_*; sem CONTENT_SECURITY_POLICY nenhum cabeçalho CSP era
# enviado. Mantemos os dois formatos para funcionar com qualquer versão instalada.
_CSP_CDNS = ("https://cdn.tailwindcss.com", "https://cdn.jsdelivr.net")  # tailwind (templates) + Swagger/Redoc
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'") + _CSP_CDNS
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'") + _CSP_CDNS
CSP_FONT_SRC = ("'self'", "data:")
CSP_IMG_SRC = ("'self'", "data:", "blob:")
CSP_CONNECT_SRC = ("'self'",) 
CSP_OBJECT_SRC = ("'none'",)
CSP_BASE_URI = ("'self'",)
CSP_FORM_ACTION = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        'default-src': CSP_DEFAULT_SRC,
        'script-src': CSP_SCRIPT_SRC,
        'style-src': CSP_STYLE_SRC,
        'font-src': CSP_FONT_SRC,
        'img-src': CSP_IMG_SRC,
        'connect-src': CSP_CONNECT_SRC,
        'object-src': CSP_OBJECT_SRC,
        'base-uri': CSP_BASE_URI,
        'form-action': CSP_FORM_ACTION,
        'frame-ancestors': CSP_FRAME_ANCESTORS,
    },
}


# --- 7.1 LOGGING (stdout -> Docker -> Dozzle) ---
# Sem handler no root, os logger.info/warning/error da app não apareciam no Dozzle.
# Mensagens seguem o padrão chave=valor (ex.: execution_log_id=42) para busca rápida.
LOG_LEVEL = env('LOG_LEVEL', default='INFO')
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'structured': {
            'format': '%(asctime)s level=%(levelname)s logger=%(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'structured',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        # Evita ruído de debug de libs HTTP que podem incluir headers/URLs com tokens.
        'urllib3': {'level': 'WARNING'},
    },
}


# --- 7.2 AUDITORIA ---
AUDIT_RETENTION_DAYS = env.int('AUDIT_RETENTION_DAYS', default=365)
SECURITY_ALERT_EMAILS = env.list('SECURITY_ALERT_EMAILS', default=[])

# URL pública do front-end: usada nos redirecionamentos do Stripe (sucesso/cancelamento).
# Antes não era definida e, em produção, o pagamento redirecionava para http://localhost:5173.
FRONTEND_URL = env('FRONTEND_URL', default='http://localhost:5173').rstrip('/')

# --- 7.3 PRIVACIDADE / LGPD ---
# Exige aceite dos documentos vigentes (cadastro e API). Desligar só em testes de integração legados.
LEGAL_ACCEPTANCE_REQUIRED = env.bool('LEGAL_ACCEPTANCE_REQUIRED', default=True)
PRIVACY_CONTACT_EMAIL = env('PRIVACY_CONTACT_EMAIL', default='privacidade@cadrius.ia.br')  # canal do encarregado (DPO)
RETENTION_EMAIL_BODY_DAYS = env.int('RETENTION_EMAIL_BODY_DAYS', default=90)
RETENTION_EXECUTION_PAYLOAD_DAYS = env.int('RETENTION_EXECUTION_PAYLOAD_DAYS', default=90)
RETENTION_INTEGRATION_LOG_DAYS = env.int('RETENTION_INTEGRATION_LOG_DAYS', default=30)

# --- 8. FILAS E BACKGROUND TASKS ---
Q_CLUSTER = {
    'name': 'cadrius_tasks',
    'workers': 4,
    'recycle': 500,
    'timeout': 60,
    # Segundos que o broker espera antes de voltar a entregar a task (Redis com receipts).
    # Tem de ser > timeout para evitar reexecuções em cima de tasks ainda a correr.
    'retry': 120,
    # max_attempts: reentregas ao nível do broker/worker (task inteira; exceção não apanhada, timeout).
    # As 3 tentativas antes de FAILED no ExecutionLog (chamadas HTTP) estão em workflows.tasks
    # (_WORKFLOW_EXTERNAL_MAX_ATTEMPTS).
    'max_attempts': 3,
    'compress': True,
    'save_limit': 250,
    'queue_limit': 500,
    'cpu_affinity': 1,
    'label': 'Django Q',
    'redis': env('REDIS_URL', default='redis://127.0.0.1:6379/0')
}



# SSRF: ações de webhook não podem chamar redes privadas/loopback. Só ativar em dev local
# (ex.: testar contra um serviço no docker) via OUTBOUND_ALLOW_PRIVATE_NETWORKS=True.
OUTBOUND_ALLOW_PRIVATE_NETWORKS = env.bool('OUTBOUND_ALLOW_PRIVATE_NETWORKS', default=DEBUG)

# --- 9. VARIÁVEIS DE INTEGRAÇÕES (FALLBACKS GLOBAIS) ---


OPENAI_API_KEY = env('OPENAI_API_KEY', default=None)
OPENAI_MODEL = env('OPENAI_MODEL', default='gpt-3.5-turbo')
# GROQ | GEMINI | OPENAI — força o provedor em generate_workflow_from_prompt; None = auto (chaves no .env).
WORKFLOW_AI_PROVIDER = env('WORKFLOW_AI_PROVIDER', default=None)

TRELLO_API_KEY = env('TRELLO_API_KEY', default=None)
TRELLO_API_TOKEN = env('TRELLO_API_TOKEN', default=None)
TRELLO_BOARD_ID = env('TRELLO_BOARD_ID', default=None)
TRELLO_LIST_ID = env('TRELLO_LIST_ID', default=None)

TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default=None)
TELEGRAM_CHAT_ID = env('TELEGRAM_CHAT_ID', default=None)

IMAP_HOST = env('IMAP_HOST', default=None)
IMAP_PORT = env.int('IMAP_PORT')
IMAP_USERNAME = env('IMAP_USERNAME', default=None)
IMAP_PASSWORD = env('IMAP_PASSWORD', default=None)


# --- 10. CONFIGURAÇÕES DE CACHE E SESSÃO (USANDO REDIS) ---
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://redis:6379/1"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
        }
    }
}

# 2. Transferindo o controle de sessão do Postgres para o Redis
# cached_db: leitura rápida pelo Redis, mas a sessão persiste no banco. Com o backend "cache" puro,
# uma queda do Redis (IGNORE_EXCEPTIONS=True) fazia o login ENTRAR EM LOOP INFINITO ao criar a
# sessão (add() sempre falhando) e um flush do Redis deslogava todos os utilizadores.
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_CACHE_ALIAS = "default"


STRIPE_PUBLIC_KEY = env('STRIPE_PUBLIC_KEY', default='')
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')
# CAD-224: meios aceitos no checkout. Assinatura: 'card' (e 'boleto' só depois de ativado no painel do Stripe).
STRIPE_PAYMENT_METHODS = env.list('STRIPE_PAYMENT_METHODS', default=['card'])
# Pesquisa jurídica (CAD-166). [VALIDAR] chave pública e URL do DataJud na documentação vigente do CNJ.
DATAJUD_API_KEY = os.environ.get('DATAJUD_API_KEY', '')
DATAJUD_BASE_URL = os.environ.get('DATAJUD_BASE_URL', 'https://api-publica.datajud.cnj.jus.br')
# "Nome|URL" separados por vírgula (só a equipe define; usuário nunca informa URL).
NEWS_FEEDS = [tuple(x.split('|', 1)) for x in os.environ.get('NEWS_FEEDS', '').split(',') if '|' in x]


# Meta Graph API (publicação no Facebook/Instagram — CAD-174). Página/Instagram da própria Cadrius (área Marketing da Gestão).
META_GRAPH_VERSION = env('META_GRAPH_VERSION', default='v21.0')
CADRIUS_META_PAGE_ID = env('CADRIUS_META_PAGE_ID', default='')
CADRIUS_META_PAGE_TOKEN = env('CADRIUS_META_PAGE_TOKEN', default='')
CADRIUS_META_IG_USER_ID = env('CADRIUS_META_IG_USER_ID', default='')

# Fiscal da Cadrius — fase 2 (NFS-e pelo emissor) e fase 3 (obrigações), CAD-175. Sem token, o registro manual (fase 1) continua.
# [VALIDAR com o contador] item de serviço, alíquota, regime e o caminho do endpoint no emissor. Nunca versionar o token.
FISCAL_NFSE_PROVIDER = env('FISCAL_NFSE_PROVIDER', default='manual')            # manual | focusnfe
FOCUSNFE_TOKEN = env('FOCUSNFE_TOKEN', default='')
FOCUSNFE_BASE = env('FOCUSNFE_BASE', default='https://homologacao.focusnfe.com.br')
FOCUSNFE_NFSE_PATH = env('FOCUSNFE_NFSE_PATH', default='nfse')                    # nfse (municipal) | nfsen (padrão nacional)
CADRIUS_FISCAL_CNPJ = env('CADRIUS_FISCAL_CNPJ', default='')
CADRIUS_FISCAL_IM = env('CADRIUS_FISCAL_IM', default='')
CADRIUS_FISCAL_COD_MUNICIPIO = env('CADRIUS_FISCAL_COD_MUNICIPIO', default='')
CADRIUS_FISCAL_ITEM_SERVICO = env('CADRIUS_FISCAL_ITEM_SERVICO', default='')
CADRIUS_FISCAL_COD_TRIBUTARIO = env('CADRIUS_FISCAL_COD_TRIBUTARIO', default='')
CADRIUS_FISCAL_ALIQUOTA_ISS = env('CADRIUS_FISCAL_ALIQUOTA_ISS', default='0')
CADRIUS_FISCAL_REGIME = env('CADRIUS_FISCAL_REGIME', default='simples')
FISCAL_CBS_PCT = env('FISCAL_CBS_PCT', default='0.9')                             # reforma tributária: alíquota-teste 2026
FISCAL_IBS_PCT = env('FISCAL_IBS_PCT', default='0.1')
FISCAL_RETENCOES_PJ = env.json('FISCAL_RETENCOES_PJ', default={})                 # ex.: {"IRRF": 1.5} — só tomador PJ
