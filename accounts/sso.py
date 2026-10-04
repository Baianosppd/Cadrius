"""Login social (Google / Microsoft) — CAD-105.

Fluxo OAuth2/OIDC *authorization code + PKCE* conduzido pelo back (o front só navega):

  1. GET  /api/v1/auth/<provider>/            → 302 ao provedor (state, nonce e PKCE em cookie assinado HttpOnly)
  2. GET  /api/v1/auth/<provider>/callback/   → troca o code, valida o id_token (assinatura, iss, aud, exp, nonce),
                                                resolve o usuário e 302 para  <FRONTEND_URL>/google/callback#access=…&refresh=…
                                                (ou #error=<código> — tokens no fragmento: não vão a logs nem ao Referer)

Política (segura por padrão): o SSO **só entra em contas que já existem** (por identidade já vinculada ou por e-mail
**verificado pelo provedor**) ou cria membro quando o domínio do e-mail pertence a um escritório cadastrado
(``Organization.allowed_domain``). Cadastro novo e plano passam pelo fluxo normal (CAD-119) — o SSO não cria conta "solta".
O aceite dos termos continua obrigatório (428 nas rotas protegidas).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from urllib.parse import urlencode

import jwt
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import HttpResponse, HttpResponseRedirect
from django.views import View
from rest_framework_simplejwt.tokens import RefreshToken

from audit import service as audit
from accounts.models import Organization, OrganizationMembership, SocialIdentity

logger = logging.getLogger(__name__)
User = get_user_model()

STATE_COOKIE = 'cadrius_sso'
STATE_MAX_AGE = 600
PUBLIC_EMAIL_DOMAINS = {'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'live.com', 'yahoo.com', 'icloud.com'}

PROVIDERS = {
    'google': {
        'authorize': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://oauth2.googleapis.com/token',
        'jwks': 'https://www.googleapis.com/oauth2/v3/certs',
        'issuers': ('https://accounts.google.com', 'accounts.google.com'),
        'scope': 'openid email profile',
        'extra': {'prompt': 'select_account'},
    },
    'microsoft': {
        'authorize': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize',
        'token': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
        'jwks': 'https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys',
        'issuers': None,  # multi-tenant: o issuer inclui o tid do token (validado em _verify_id_token)
        'scope': 'openid email profile',
        'extra': {'prompt': 'select_account'},
    },
}


class SsoError(Exception):
    """Falha esperada do fluxo: ``code`` vai ao front (#error=code); nunca detalhes internos."""

    def __init__(self, code: str, log: str = ''):
        super().__init__(log or code)
        self.code = code


# ----------------------------------------------------------------------------- configuração
def _cfg(provider: str):
    if provider not in PROVIDERS:
        raise SsoError('provider_unknown')
    prefix = provider.upper()
    client_id = getattr(settings, f'{prefix}_CLIENT_ID', '') or ''
    client_secret = getattr(settings, f'{prefix}_CLIENT_SECRET', '') or ''
    if not client_id or not client_secret:
        raise SsoError('sso_disabled', f'{provider} sem client id/secret')
    tenant = getattr(settings, 'MICROSOFT_TENANT', 'common') or 'common'
    base = PROVIDERS[provider]
    return {
        'client_id': client_id, 'client_secret': client_secret, 'tenant': tenant,
        **{k: (v.format(tenant=tenant) if isinstance(v, str) else v) for k, v in base.items()},
    }


def _api_base(request) -> str:
    configured = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/')
    return configured or request.build_absolute_uri('/').rstrip('/')


def _redirect_uri(request, provider: str) -> str:
    return f'{_api_base(request)}/api/v1/auth/{provider}/callback/'


def _front_redirect(fragment: dict) -> HttpResponse:
    response = HttpResponseRedirect(f'{settings.FRONTEND_URL}/google/callback#{urlencode(fragment)}')
    response.delete_cookie(STATE_COOKIE)
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    return response


# ----------------------------------------------------------------------------- PKCE / state
def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


def _build_auth_url(request, provider: str):
    cfg = _cfg(provider)
    state, nonce, verifier = (secrets.token_urlsafe(24) for _ in range(3))
    params = {
        'client_id': cfg['client_id'], 'redirect_uri': _redirect_uri(request, provider), 'response_type': 'code',
        'scope': cfg['scope'], 'state': state, 'nonce': nonce,
        'code_challenge': _pkce_challenge(verifier), 'code_challenge_method': 'S256', **cfg['extra'],
    }
    cookie = signing.dumps({'p': provider, 's': state, 'n': nonce, 'v': verifier}, salt='cadrius.sso')
    return f"{cfg['authorize']}?{urlencode(params)}", cookie


def _read_cookie(request, provider: str, state: str) -> dict:
    raw = request.COOKIES.get(STATE_COOKIE)
    if not raw or not state:
        raise SsoError('state_invalid', 'cookie/state ausente')
    try:
        data = signing.loads(raw, salt='cadrius.sso', max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise SsoError('state_invalid', 'cookie adulterado/expirado') from exc
    if data.get('p') != provider or not secrets.compare_digest(str(data.get('s')), state):
        raise SsoError('state_invalid', 'state não confere')
    return data


# ----------------------------------------------------------------------------- troca do code e validação do token
def _exchange_code(request, provider: str, code: str, verifier: str) -> dict:
    cfg = _cfg(provider)
    try:
        resp = requests.post(cfg['token'], data={
            'grant_type': 'authorization_code', 'code': code, 'redirect_uri': _redirect_uri(request, provider),
            'client_id': cfg['client_id'], 'client_secret': cfg['client_secret'], 'code_verifier': verifier,
        }, headers={'Accept': 'application/json'}, timeout=10)
    except requests.RequestException as exc:
        raise SsoError('provider_unreachable', exc.__class__.__name__) from exc
    if resp.status_code != 200:
        raise SsoError('code_rejected', f'token endpoint {resp.status_code}')
    return resp.json()


def _verify_id_token(provider: str, id_token: str, nonce: str) -> dict:
    cfg = _cfg(provider)
    try:
        key = jwt.PyJWKClient(cfg['jwks']).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(id_token, key, algorithms=['RS256'], audience=cfg['client_id'],
                            options={'require': ['exp', 'iss', 'aud', 'sub']})
    except (jwt.PyJWTError, requests.RequestException, ValueError) as exc:
        raise SsoError('token_invalid', exc.__class__.__name__) from exc
    issuer = claims.get('iss', '')
    if provider == 'google':
        ok = issuer in cfg['issuers']
    else:  # Microsoft: https://login.microsoftonline.com/<tid>/v2.0 com o mesmo tid do token
        ok = bool(claims.get('tid')) and issuer == f"https://login.microsoftonline.com/{claims['tid']}/v2.0"
    if not ok:
        raise SsoError('token_invalid', 'issuer inesperado')
    if not secrets.compare_digest(str(claims.get('nonce', '')), nonce):
        raise SsoError('token_invalid', 'nonce não confere')
    return claims


def _identity(provider: str, claims: dict):
    """(subject estável, e-mail, e-mail_verificado). Microsoft não afirma verificação: exige a claim opcional xms_edov."""
    email = (claims.get('email') or claims.get('preferred_username') or '').strip().lower()
    if provider == 'google':
        verified = claims.get('email_verified') in (True, 'true')
        subject = claims['sub']
    else:
        verified = claims.get('xms_edov') in (True, 1, '1', 'true')
        subject = f"{claims.get('tid')}:{claims.get('oid') or claims['sub']}"
    return subject, email, verified


# ----------------------------------------------------------------------------- resolução do usuário
def _resolve_user(provider: str, subject: str, email: str, verified: bool, claims: dict):
    link = SocialIdentity.objects.select_related('user').filter(provider=provider, subject=subject).first()
    if link:
        return link.user

    if not email or '@' not in email or not verified:
        raise SsoError('email_unverified', 'provedor não atestou o e-mail')

    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        domain = email.rsplit('@', 1)[-1]
        org = None if domain in PUBLIC_EMAIL_DOMAINS else Organization.objects.filter(allowed_domain__iexact=domain).first()
        if org is None:
            raise SsoError('no_account', 'sem conta e domínio sem escritório cadastrado')
        user = User(username=email, email=email, first_name=(claims.get('given_name') or '')[:150],
                    last_name=(claims.get('family_name') or '')[:150])
        user.set_unusable_password()
        user.save()
        OrganizationMembership.objects.get_or_create(user=user, organization=org, defaults={'role': 'MEMBER'})
    SocialIdentity.objects.get_or_create(provider=provider, subject=subject,
                                         defaults={'user': user, 'email_at_link': email})
    return user


# ----------------------------------------------------------------------------- views
class SsoStartView(View):
    http_method_names = ['get']

    def get(self, request, provider):
        try:
            url, cookie = _build_auth_url(request, provider)
        except SsoError as exc:
            audit.log('auth.sso.login', actor_type='anonymous', outcome='denied', reason=exc.code)
            return _front_redirect({'error': exc.code})
        response = HttpResponseRedirect(url)
        response.set_cookie(STATE_COOKIE, cookie, max_age=STATE_MAX_AGE, httponly=True, samesite='Lax',
                            secure=not settings.DEBUG)
        response['Cache-Control'] = 'no-store'
        return response


class SsoCallbackView(View):
    http_method_names = ['get']

    def get(self, request, provider):
        try:
            if request.GET.get('error'):
                raise SsoError('access_denied', f"provedor devolveu {request.GET.get('error')[:40]}")
            data = _read_cookie(request, provider, request.GET.get('state', ''))
            code = request.GET.get('code', '')
            if not code:
                raise SsoError('code_rejected', 'sem code')
            tokens = _exchange_code(request, provider, code, data['v'])
            claims = _verify_id_token(provider, tokens.get('id_token', ''), data['n'])
            subject, email, verified = _identity(provider, claims)
            user = _resolve_user(provider, subject, email, verified, claims)
            if not user.is_active:
                raise SsoError('account_disabled', 'usuário inativo')
        except SsoError as exc:
            logger.warning('SSO %s recusado: %s', provider, exc)
            audit.log('auth.sso.login', actor_type='anonymous', outcome='denied', reason=f'{provider}: {exc.code}')
            return _front_redirect({'error': exc.code})

        refresh = RefreshToken.for_user(user)
        audit.log('auth.sso.login', actor=user, reason=provider, legal_basis='contrato')
        return _front_redirect({'access': str(refresh.access_token), 'refresh': str(refresh)})
