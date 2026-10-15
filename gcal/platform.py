"""App OAuth do Google mantido pelo Cadrius (CAD-230).

Antes, cada escritório criava um projeto no Google Cloud, ativava a API, cadastrava o redirect e colava ID e segredo no
Cadrius. Com o app da plataforma configurado no servidor, a pessoa só clica em "Conectar Google" e autoriza.

Ordem: ``GOOGLE_WORKSPACE_CLIENT_ID/SECRET`` (app dedicado, recomendado) → ``GOOGLE_CLIENT_ID/SECRET`` (o mesmo do login
com Google). Escritórios que preferem o próprio app continuam podendo cadastrá-lo (tem prioridade).
"""
from __future__ import annotations

from django.conf import settings

# Escopos pedidos ao conectar. calendar.events: ler/criar/alterar compromissos. drive.file: só os arquivos (planilhas e
# documentos) que o PRÓPRIO Cadrius criar — não dá acesso ao resto do Drive (escopo não sensível no Google).
CALENDAR = 'https://www.googleapis.com/auth/calendar.events'
DRIVE_FILE = 'https://www.googleapis.com/auth/drive.file'
# CAD-234: leitura do Drive, pedida SÓ quando a pessoa vai importar a carteira de clientes das pastas (autorização incremental).
# É escopo "restrito" no Google: em produção pública o app precisa da verificação do Google; até lá, só usuários de teste do app.
DRIVE_READONLY = 'https://www.googleapis.com/auth/drive.readonly'
IDENTITY = 'openid email'
EXTRA_ACCESS = {'drive_leitura': DRIVE_READONLY}


def platform_credentials() -> tuple[str, str]:
    cid = getattr(settings, 'GOOGLE_WORKSPACE_CLIENT_ID', '') or getattr(settings, 'GOOGLE_CLIENT_ID', '') or ''
    secret = getattr(settings, 'GOOGLE_WORKSPACE_CLIENT_SECRET', '') or getattr(settings, 'GOOGLE_CLIENT_SECRET', '') or ''
    return cid, secret


def drive_import_enabled() -> bool:
    return bool(getattr(settings, 'GOOGLE_DRIVE_IMPORT_ENABLED', True))


def platform_available() -> bool:
    cid, secret = platform_credentials()
    return bool(cid and secret)


def scopes(acesso: str = '') -> str:
    extra = getattr(settings, 'GOOGLE_EXTRA_SCOPES', '') or ''
    if acesso in EXTRA_ACCESS and drive_import_enabled():
        extra = f'{extra} {EXTRA_ACCESS[acesso]}'
    wanted = [IDENTITY, CALENDAR]
    if getattr(settings, 'GOOGLE_DOCS_SHEETS_ENABLED', True):
        wanted.append(DRIVE_FILE)
    return ' '.join(dict.fromkeys(' '.join(wanted + [extra]).split()))


def app_for(org, *, create=True):
    """App do escritório (o dele, se cadastrou; senão o da plataforma, criado sob demanda)."""
    from gcal.models import GoogleCalendarApp
    app = GoogleCalendarApp.objects.filter(organization=org).first()
    if app is not None:
        if app.uses_platform and not platform_available():
            return None
        return app if app.enabled else None
    if not create or not platform_available():
        return None
    cid, _ = platform_credentials()
    return GoogleCalendarApp.objects.create(organization=org, client_id=cid, client_secret='', uses_platform=True)
