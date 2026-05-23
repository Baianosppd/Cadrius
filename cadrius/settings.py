import os
from pathlib import Path
import environ
from datetime import timedelta
import sentry_sdk 
from sentry_sdk.integrations.django import DjangoIntegration

# --- 1. INICIALIZAÇÃO DO AMBIENTE ---
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
    IMAP_PORT=(int, 993),
    # Corpo máx. (JSON / multipart) alinhado com Traefik buffering (~2MB); evita payloads enormes.
    DATA_UPLOAD_MAX_MEMORY_BYTES=(int, 2 * 1024 * 1024),
)

environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# --- 2. MONITORAMENTO (SENTRY) ---
SENTRY_DSN = env('SENTRY_DSN', default=None)
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=True
    )

# --- 3. CORE SETTINGS E SEGURANÇA BÁSICA ---
SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-prod')
DEBUG = env('DEBUG')
DATA_UPLOAD_MAX_MEMORY_SIZE = env('DATA_UPLOAD_MAX_MEMORY_BYTES')
FILE_UPLOAD_MAX_MEMORY_SIZE = env('DATA_UPLOAD_MAX_MEMORY_BYTES')
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '.ngrok-free.app', '.ngrok.io', 'nonvinous-debbie-unrelated.ngrok-free.dev','cadrius.local']

CSRF_TRUSTED_ORIGINS = [
    'http://localhost',
    'http://127.0.0.1',
    'https://*.ngrok-free.app',
    'https://*.ngrok.io',
    'https://nonvinous-debbie-unrelated.ngrok-free.dev'
]


SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

ENCRYPTION_KEY = env('ENCRYPTION_KEY', default=None) 

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
    'tasks', # Módulo de Tarefas Agendadas e Background Jobs
    'workflows',  #  Motor de Automação
    'webhooks',  # Recebedor de Eventos Externos
    'billing',# Módulo de Assinaturas e Pagamentos
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',              
    'django.middleware.security.SecurityMiddleware',
    'csp.middleware.CSPMiddleware',                       
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    
    # Middleware de Multi-tenancy 
    'cadrius.middleware.TenantMiddleware',
    
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
EVOLUTION_API_GLOBAL_KEY = env('EVOLUTION_API_GLOBAL_KEY', default='cadrius_mestre_secreto_123')

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


# --- 6. INTERNACIONALIZAÇÃO E ARQUIVOS ---
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# --- 7. API, JWT E CORS ---
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Throttling por scope (ScopedRateThrottle / SimpleRateThrottle com ``scope``).
    'DEFAULT_THROTTLE_RATES': {
        'webhook': '200/min',
        'webhook_catch': '60/min',
    },
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
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

CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "https://cdn.tailwindcss.com")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "https://cdn.tailwindcss.com")
CSP_FONT_SRC = ("'self'", "data:")
CSP_IMG_SRC = ("'self'", "data:", "blob:")
CSP_CONNECT_SRC = ("'self'",) 


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
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"


STRIPE_PUBLIC_KEY = env('STRIPE_PUBLIC_KEY', default='')
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')