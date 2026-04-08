"""
Validação de corpo bruto para webhooks externos (JSON genérico).
"""

from __future__ import annotations

import json
from typing import Any


class WebhookPayloadError(Exception):
    """Payload ausente, inválido ou com estrutura não suportada na raiz."""

    def __init__(self, message: str, code: str = 'invalid_payload'):
        self.message = message
        self.code = code
        super().__init__(message)


def parse_and_validate_webhook_json(raw_body: bytes | memoryview) -> dict[str, Any]:
    """
    1) Garante JSON parseável.
    2) Exige objeto JSON na raiz (dict), não array nem primitivo isolado.
    """
    if not raw_body:
        raise WebhookPayloadError('Corpo da requisição vazio.', code='empty_body')

    try:
        text = raw_body.decode('utf-8')
    except UnicodeDecodeError as e:
        raise WebhookPayloadError('Corpo não é UTF-8 válido.', code='invalid_encoding') from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise WebhookPayloadError('JSON inválido ou malformado.', code='invalid_json') from e

    if not isinstance(data, dict):
        raise WebhookPayloadError(
            'A raiz do JSON deve ser um objeto ({}), não array nem valor simples.',
            code='invalid_structure',
        )

    return data
