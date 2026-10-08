"""Cliente mínimo da API do Google (OAuth2 + Calendar v3). Fica isolado para ser simulado nos testes."""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
CAL_BASE = 'https://www.googleapis.com/calendar/v3'
SCOPE = 'https://www.googleapis.com/auth/calendar.events'
TIMEOUT = 15


class GoogleAuthError(Exception):
    """Token revogado/expirado (invalid_grant) ou credenciais do app inválidas: o usuário precisa reconectar.
    ``code`` traz o código de erro do Google (invalid_client, redirect_uri_mismatch, invalid_grant…), sem segredos."""

    def __init__(self, message='', code=''):
        super().__init__(message)
        self.code = code


class GoogleRetryable(Exception):
    """Falha transitória (429/5xx/rede): a tarefa do Django-Q tenta de novo."""


class GoogleNotFound(Exception):
    """Evento inexistente (404/410)."""


def exchange_code(client_id, client_secret, code, redirect_uri, verifier):
    resp = requests.post(TOKEN_URL, data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri,
                                          'client_id': client_id, 'client_secret': client_secret, 'code_verifier': verifier},
                         timeout=TIMEOUT)
    if resp.status_code != 200:
        try:
            code = str(resp.json().get('error', ''))[:40]
        except ValueError:
            code = ''
        raise GoogleAuthError(f'token endpoint {resp.status_code} {code}', code=code)
    return resp.json()


def refresh_access_token(client_id, client_secret, refresh_token):
    try:
        resp = requests.post(TOKEN_URL, data={'grant_type': 'refresh_token', 'refresh_token': refresh_token,
                                              'client_id': client_id, 'client_secret': client_secret}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise GoogleRetryable(exc.__class__.__name__) from exc
    if resp.status_code in (400, 401):
        raise GoogleAuthError('invalid_grant' if 'invalid_grant' in resp.text else 'credenciais recusadas')
    if resp.status_code != 200:
        raise GoogleRetryable(f'token endpoint {resp.status_code}')
    data = resp.json()
    return data['access_token'], int(data.get('expires_in', 3600))


def revoke(token):
    try:
        requests.post(REVOKE_URL, data={'token': token}, timeout=TIMEOUT)
    except requests.RequestException:
        logger.info('Revogação no Google falhou (token já inválido ou rede)')


def calendar_call(access_token, method, path, *, params=None, json=None):
    return api_call(access_token, method, f'{CAL_BASE}{path}', params=params, json=json)


SHEETS_BASE = 'https://sheets.googleapis.com/v4'
DOCS_BASE = 'https://docs.googleapis.com/v1'
ALLOWED_BASES = (CAL_BASE, SHEETS_BASE, DOCS_BASE)


def api_call(access_token, method, url, *, params=None, json=None):
    """Chamada às APIs do Google (Agenda, Planilhas, Documentos — CAD-230). Só para as bases conhecidas."""
    if not url.startswith(ALLOWED_BASES):
        raise ValueError('URL fora das APIs do Google permitidas')
    try:
        resp = requests.request(method, url, params=params, json=json, timeout=TIMEOUT,
                                headers={'Authorization': f'Bearer {access_token}'})
    except requests.RequestException as exc:
        raise GoogleRetryable(exc.__class__.__name__) from exc
    if resp.status_code in (404, 410):
        raise GoogleNotFound(url)
    if resp.status_code == 401:
        raise GoogleAuthError('access token recusado')
    if resp.status_code in (429, 500, 502, 503, 504) or (resp.status_code == 403 and 'rateLimit' in resp.text):
        raise GoogleRetryable(f'google {resp.status_code}')
    if resp.status_code == 403:
        raise GoogleAuthError('acesso negado (escopo não autorizado ou API desativada no projeto do Google)')
    if resp.status_code >= 400:
        raise GoogleRetryable(f'google {resp.status_code}')
    return resp.json() if resp.content else {}
