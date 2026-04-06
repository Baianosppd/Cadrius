import os
from pathlib import Path
import environ
from datetime import timedelta
import sentry_sdk 
from sentry_sdk.integrations.django import DjangoIntegration

# --- 1. INICIALIZAÇÃO DO AMBIENTE ---
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
    IMAP_PORT=(int, 993),
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
ALLOWED_HOSTS = env('ALLOWED_HOSTS')

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
    'drf_yasg',
    'django_q',
    'axes',
    'drf_spectacular',

    # Local apps (O Core do Cadrius)
    'core',
    'accounts',
    'emails',
    'integrations',
    'extraction',
    'tasks',
    'workflows',  #  Motor de Automação
    'webhooks',  # Recebedor de Eventos Externos
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

# --- 5. BANCO DE DADOS E AUTENTICAÇÃO ---
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR}/db.sqlite3')
}

AUTH_USER_MODEL = 'accounts.CustomUser'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesBackend', 
    'django.contrib.auth.backends.ModelBackend',
]

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
    'compress': True,
    'save_limit': 250,
    'queue_limit': 500,
    'cpu_affinity': 1,
    'label': 'Django Q',
    'redis': env('REDIS_URL', default='redis://127.0.0.1:6379/0')
}



SENTRY_DSN = os.getenv('SENTRY_DSN')

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        
        # Ajuste a taxa de amostragem de performance (0.0 a 1.0)
        traces_sample_rate=0.2,
        
        # Se for True, envia informações do usuário logado que causou o erro
        send_default_pii=True,
        
        # Define o ambiente (Development, Staging, Production)
        environment=os.getenv('ENVIRONMENT', 'development')
    )


# --- 9. VARIÁVEIS DE INTEGRAÇÕES (FALLBACKS GLOBAIS) ---
# Nota Arquitetural: Preferir sempre buscar credenciais dos modelos 
# AppConnection e MailBox do banco de dados ao invés daqui.
OPENAI_API_KEY = env('OPENAI_API_KEY', default=None)
OPENAI_MODEL = env('OPENAI_MODEL', default='gpt-3.5-turbo')

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