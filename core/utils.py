"""Criptografia de dados em repouso (Fernet / AES-128-CBC + HMAC-SHA256).

Usada para credenciais de terceiros (senhas IMAP, tokens de integrações). A chave vem de
``ENCRYPTION_KEY`` (chave Fernet urlsafe-base64 de 32 bytes). Suporta **rotação**: defina
``ENCRYPTION_KEY="nova,antiga"`` — a primeira cifra, todas decifram.

Gerar uma chave:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

logger = logging.getLogger(__name__)
_warned_derived_key = False

# Prefixo que distingue valor cifrado de legado em texto puro (migração gradual segura).
ENC_PREFIX = 'enc::'


def _build_fernet() -> MultiFernet:
    raw = (getattr(settings, 'ENCRYPTION_KEY', None) or '').strip()
    if raw:
        keys = [k.strip().encode() for k in raw.split(',') if k.strip()]
    elif getattr(settings, 'ENCRYPTION_ALLOW_DERIVED_KEY', False):
        # Só desenvolvimento/testes: deriva uma chave estável da SECRET_KEY.
        global _warned_derived_key
        if not _warned_derived_key:
            _warned_derived_key = True
            logger.warning('ENCRYPTION_KEY ausente: a usar chave derivada da SECRET_KEY (apenas DEBUG).')
        derived = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
        keys = [derived]
    else:
        raise ImproperlyConfigured('ENCRYPTION_KEY é obrigatória em produção.')
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            'ENCRYPTION_KEY inválida: use uma chave Fernet (32 bytes em urlsafe-base64).'
        ) from exc


def encrypt_data(plaintext: str) -> str:
    return ENC_PREFIX + _build_fernet().encrypt(plaintext.encode()).decode()


def decrypt_data(value: str) -> str:
    """Decifra ``value``. Valor sem prefixo é legado em texto puro e devolve-se como está."""
    if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
        return value
    try:
        return _build_fernet().decrypt(value[len(ENC_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError('Não foi possível decifrar o valor (chave errada ou dado corrompido).') from exc


class EncryptedTextField(models.TextField):
    """Texto cifrado na base de dados, transparente em Python. Não suporta filtros por valor."""

    def from_db_value(self, value, expression, connection):
        return decrypt_data(value) if value else value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        return value if value.startswith(ENC_PREFIX) else encrypt_data(value)


class EncryptedJSONField(models.TextField):
    """JSON (dict/list) cifrado na base de dados; em Python comporta-se como JSONField."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('default', dict)
        super().__init__(*args, **kwargs)

    def from_db_value(self, value, expression, connection):
        if value in (None, ''):
            return {} if value == '' else None
        if isinstance(value, str):
            value = decrypt_data(value)
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def to_python(self, value):
        if isinstance(value, str):
            try:
                return json.loads(decrypt_data(value))
            except json.JSONDecodeError:
                return value
        return value

    def get_prep_value(self, value):
        if value is None:
            return None
        if isinstance(value, str) and value.startswith(ENC_PREFIX):
            return value
        return encrypt_data(json.dumps(value))

    def value_to_string(self, obj):
        return json.dumps(self.value_from_object(obj))
