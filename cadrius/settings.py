import os
from pathlib import Path
import environ
from datetime import timedelta

# 1. Inicialização do Ambiente
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Inicializa django-environ
env = environ.Env(
    # Define valores padrão e tipos esperados (Casting automático)
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
    # Integrações
    IMAP_PORT=(int, 993),
)

# Lê o arquivo .env se ele existir
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# --- CORE SETTINGS ---

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-prod')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')

# Lista de hosts permitidos (vem do .env separado por vírgula)
ALLOWED_HOSTS = env('ALLOWED_HOSTS')


# --- APPLICATION DEFINITION ---

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'corsheaders',            # Para lidar com Frontend React
    'rest_framework',         # API Core
    'rest_framework_simplejwt', # Autenticação
    'drf_yasg',               # Documentação Swagger
    'django_q',               # Thales: Task Broker

    # Local apps (Cadrius Modules)
    'core',
    'accounts',
    'emails',
    'integrations',
    'extraction',
    'tasks',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',              # Deve ser o primeiro!
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    
    # Jullio: Middleware de Multi-tenancy (Deve vir APÓS Auth e ANTES de View)
    'cadrius.middleware.TenantMiddleware',
    
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'cadrius.urls'

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

WSGI_APPLICATION = 'cadrius.wsgi.application'


# --- DATABASE & AUTH ---

# Database
# Usa env.db() que lê a string DATABASE_URL automaticamente
# Suporta postgres://, sqlite://, etc.
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR}/db.sqlite3')
}

# Jullio: Crucial para o modelo de SaaS. Aponta para o nosso usuário customizado.
AUTH_USER_MODEL = 'accounts.CustomUser'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    { 'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator', },
]


# --- INTERNATIONALIZATION ---

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True


# --- STATIC & MEDIA FILES ---

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles') # Para Docker/Nginx

MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media') # Para Uploads de arquivos

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- REST FRAMEWORK & SECURITY ---

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
}

# Swagger Settings
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

# CORS Settings (React Frontend)
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS')


# --- ASYNC TASKS (THALES) ---

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


# --- INTEGRAÇÕES ---

# OpenAI
OPENAI_API_KEY = env('OPENAI_API_KEY', default=None)
OPENAI_MODEL = env('OPENAI_MODEL', default='gpt-3.5-turbo')

# Trello
TRELLO_API_KEY = env('TRELLO_API_KEY', default=None)
TRELLO_API_TOKEN = env('TRELLO_API_TOKEN', default=None)
TRELLO_BOARD_ID = env('TRELLO_BOARD_ID', default=None)
TRELLO_LIST_ID = env('TRELLO_LIST_ID', default=None)

# Telegram
TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default=None)
TELEGRAM_CHAT_ID = env('TELEGRAM_CHAT_ID', default=None)

# E-mail (IMAP)
IMAP_HOST = env('IMAP_HOST', default=None)
IMAP_PORT = env.int('IMAP_PORT')
IMAP_USERNAME = env('IMAP_USERNAME', default=None)
IMAP_PASSWORD = env('IMAP_PASSWORD', default=None)