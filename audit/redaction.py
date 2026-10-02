"""Mascaramento de dados pessoais/segredos ANTES de qualquer registo de auditoria ou log.

Princípio (LGPD art. 6º III — necessidade): a trilha regista *quem fez o quê*, nunca o conteúdo
de dados pessoais. Referências (ids, nomes de campos, hashes) em vez de valores.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

from django.conf import settings

REDACTED = '<redacted>'

# Chaves cujo VALOR nunca é registado (comparação por substring, case-insensitive).
SENSITIVE_KEY_PARTS = (
    'password', 'senha', 'secret', 'token', 'authorization', 'credential', 'api_key', 'apikey',
    'cookie', 'cpf', 'cnpj', 'body', 'payload', 'refresh', 'access', 'key', 'phone', 'telefone',
)

_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_CPF_RE = re.compile(r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b')
_JWT_RE = re.compile(r'\beyJ[\w-]+\.[\w-]+\.[\w-]+\b')


def stable_hash(value: str) -> str:
    """HMAC-SHA256 (chave = SECRET_KEY): permite correlacionar sem revelar o valor."""
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, (value or '').encode(), hashlib.sha256).hexdigest()


def mask_email(email: str) -> str:
    """j***@dominio.com — mantém o domínio (útil para triagem) e esconde a identidade."""
    if not email or '@' not in email:
        return ''
    local, _, domain = email.partition('@')
    return f'{local[:1]}***@{domain}'


def scrub_text(text: str) -> str:
    text = _JWT_RE.sub(REDACTED, text)
    text = _CPF_RE.sub(REDACTED, text)
    return _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), text)


def redact(value: Any, *, _key: str = '') -> Any:
    """Redige recursivamente dicts/listas/strings."""
    lowered = _key.lower()
    if lowered and any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, _key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v, _key=_key) for v in value]
    if isinstance(value, str):
        return scrub_text(value)[:500]
    return value
