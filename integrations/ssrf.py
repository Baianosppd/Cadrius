"""Proteção contra SSRF para URLs configuradas por utilizadores (ações de webhook).

Um utilizador (ou um prompt injetado na geração de workflows por IA) pode definir
``Action.endpoint_url``. Sem validação, o worker faria pedidos à rede interna
(Redis, Postgres, Evolution API, metadados cloud 169.254.169.254, etc.).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from django.conf import settings


class UnsafeURLError(ValueError):
    """URL de destino não permitida (esquema inválido ou endereço interno)."""


def _is_forbidden_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_outbound_url(url: str, *, resolve: bool = True) -> str:
    """Valida ``url`` e devolve-a; levanta ``UnsafeURLError`` se for insegura.

    ``resolve=False`` valida só esquema/credenciais (sem DNS), útil no cadastro via API.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError('URL vazia.')

    parsed = urlparse(url.strip())
    if parsed.scheme not in ('http', 'https'):
        raise UnsafeURLError('Apenas URLs http/https são permitidas.')
    if parsed.username or parsed.password:
        raise UnsafeURLError('URLs com credenciais embutidas não são permitidas.')
    host = parsed.hostname
    if not host:
        raise UnsafeURLError('URL sem host.')

    if not resolve or getattr(settings, 'OUTBOUND_ALLOW_PRIVATE_NETWORKS', False):
        return url

    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == 'https' else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f'Não foi possível resolver o host: {host}') from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _is_forbidden_ip(ip):
            raise UnsafeURLError('O destino resolve para um endereço de rede interno/reservado.')
    return url
