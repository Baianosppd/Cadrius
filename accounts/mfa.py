"""MFA por TOTP (RFC 6238) — CAD-169. Sem dependência externa para o código; ``qrcode`` só desenha o QR.

Fluxo de login: senha (ou SSO) certa + MFA ativo → ``mfa_token`` assinado (5 min) em vez dos tokens → ``/auth/mfa/verify/``
com o código do app (ou um código de recuperação) → tokens com a marca ``amr=mfa``. A Gestão Cadrius exige essa marca.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.models import update_last_login
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

STEP = 30
DIGITS = 6
WINDOW = 1                 # aceita o código anterior/seguinte (relógio do celular adiantado/atrasado)
CHALLENGE_MAX_AGE = 300
CHALLENGE_SALT = 'cadrius.mfa.challenge'
MAX_ATTEMPTS = 5
RECOVERY_CODES = 10
ISSUER = 'Cadrius'


# ----------------------------------------------------------------------------- TOTP
def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack('>Q', step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    if len(code) != DIGITS:
        return None
    current = int((now if now is not None else time.time()) // STEP)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str) -> str:
    label = quote(f'{ISSUER}:{account}')
    return f'otpauth://totp/{label}?secret={secret}&issuer={ISSUER}&algorithm=SHA1&digits={DIGITS}&period={STEP}'


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return img.to_string(encoding='unicode')


# ----------------------------------------------------------------------------- estado do usuário
def enabled(user) -> bool:
    if not (user and user.is_authenticated):
        return False
    from accounts.models import MFADevice
    return MFADevice.objects.filter(user=user, confirmed_at__isnull=False).exists()   # sem cache do objeto: estado sempre atual


def required(user) -> bool:
    """Equipe Cadrius: sempre. Dono/administrador de escritório: quando ``MFA_REQUIRED_FOR_MANAGERS`` (rollout gradual)."""
    if not (user and user.is_authenticated):
        return False
    if user.is_staff:
        return True
    if getattr(settings, 'MFA_REQUIRED_FOR_MANAGERS', False):
        from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
        membership = get_active_membership(user)
        return bool(membership and membership.role in MANAGE_TEAM_ROLES)
    return False


def request_has_mfa(request) -> bool:
    """O token desta requisição veio de um login com MFA?"""
    token = getattr(request, 'auth', None)
    try:
        return bool(token is not None and token.get('amr') == 'mfa')
    except AttributeError:
        return False


def _hash_recovery(user, code: str) -> str:
    normalized = code.replace('-', '').replace(' ', '').lower()
    return hmac.new(settings.SECRET_KEY.encode(), f'{user.pk}:{normalized}'.encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(user) -> list[str]:
    from accounts.models import MFARecoveryCode
    codes = [f'{secrets.token_hex(2)}-{secrets.token_hex(2)}' for _ in range(RECOVERY_CODES)]
    with transaction.atomic():
        MFARecoveryCode.objects.filter(user=user).delete()
        MFARecoveryCode.objects.bulk_create([MFARecoveryCode(user=user, code_hash=_hash_recovery(user, c)) for c in codes])
    return codes


def recovery_left(user) -> int:
    return user.mfa_recovery_codes.filter(used_at__isnull=True).count()


def check_code(user, code: str) -> str | None:
    """Confere código do app (com proteção contra reuso) ou de recuperação (uso único). Devolve 'totp', 'recovery' ou None."""
    from accounts.models import MFADevice, MFARecoveryCode
    code = str(code or '').strip()
    with transaction.atomic():
        device = MFADevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=False).first()
        if device is None:
            return None
        step = matching_step(device.secret, code)
        if step is not None:
            if step <= device.last_step:
                return None                       # mesmo código usado de novo
            device.last_step = step
            device.save(update_fields=['last_step'])
            return 'totp'
        if '-' in code or len(code) == 8:
            rc = MFARecoveryCode.objects.select_for_update().filter(
                user=user, code_hash=_hash_recovery(user, code), used_at__isnull=True).first()
            if rc:
                rc.used_at = timezone.now()
                rc.save(update_fields=['used_at'])
                return 'recovery'
    return None


def disable(user) -> None:
    from accounts.models import MFADevice, MFARecoveryCode
    MFADevice.objects.filter(user=user).delete()
    MFARecoveryCode.objects.filter(user=user).delete()


# ----------------------------------------------------------------------------- desafio de login e tokens
def issue_challenge(user, via: str) -> str:
    return signing.dumps({'u': str(user.pk), 'n': secrets.token_hex(8), 'via': via}, salt=CHALLENGE_SALT)


def read_challenge(token: str) -> dict | None:
    try:
        data = signing.loads(token or '', salt=CHALLENGE_SALT, max_age=CHALLENGE_MAX_AGE)
    except signing.BadSignature:
        return None
    if cache.get(f'mfa:dead:{data.get("n")}'):
        return None
    return data


def register_failure(challenge: dict) -> int:
    key = f'mfa:fail:{challenge["n"]}'
    try:
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, CHALLENGE_MAX_AGE)
    except Exception:  # noqa: BLE001 — sem cache, conta como esgotado (falha fechada)
        attempts = MAX_ATTEMPTS
    if attempts >= MAX_ATTEMPTS:
        kill_challenge(challenge)
    return attempts


def kill_challenge(challenge: dict) -> None:
    try:
        cache.set(f'mfa:dead:{challenge["n"]}', 1, CHALLENGE_MAX_AGE)
    except Exception:  # noqa: BLE001
        pass


def issue_tokens(user, *, mfa: bool) -> dict:
    refresh = RefreshToken.for_user(user)
    if mfa:
        refresh['amr'] = 'mfa'                     # copiado para o access token (e nos refresh seguintes)
    update_last_login(None, user)
    data = {'access': str(refresh.access_token), 'refresh': str(refresh)}
    if getattr(user, 'must_change_password', False):
        data['password_change_required'] = True      # senha temporária da TI: o app abre a troca obrigatória
    return data


MFA_DENIED = {'detail': 'Ative a verificação em duas etapas e entre de novo para acessar a Gestão Cadrius.', 'code': 'mfa_required'}


def staff_session_ok(request) -> bool:
    """Área da equipe Cadrius: a sessão precisa ter passado pelo MFA (token com ``amr=mfa``)."""
    return request_has_mfa(request)
