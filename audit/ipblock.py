"""Bloqueio de IP pela TI (CAD-221). Lista curta, lida do cache (30 s) para não consultar o banco a cada pedido."""
from __future__ import annotations

import ipaddress
import logging

from django.core.cache import cache
from django.db.models import F, Q
from django.http import JsonResponse
from django.utils import timezone

from audit.context import client_ip

logger = logging.getLogger(__name__)
CACHE_KEY = 'security:blocked_ips'
EXEMPT = ('/healthz', '/readyz')


def parse(value: str):
    """IP ou CIDR → rede; levanta ValueError se inválido."""
    return ipaddress.ip_network(str(value).strip(), strict=False)


def active_networks() -> list[tuple[str, object]]:
    cached = cache.get(CACHE_KEY)
    if cached is None:
        from audit.models import BlockedIP
        now = timezone.now()
        cached = list(BlockedIP.objects.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).values_list('network', flat=True))
        cache.set(CACHE_KEY, cached, 30)
    out = []
    for net in cached:
        try:
            out.append((net, parse(net)))
        except ValueError:
            continue
    return out


def match_network(ip: str | None, net) -> bool:
    try:
        addr = ipaddress.ip_address(ip or '')
    except ValueError:
        return False
    return addr.version == net.version and addr in net


def match(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    for raw, net in active_networks():
        if addr.version == net.version and addr in net:
            return raw
    return None


def invalidate():
    cache.delete(CACHE_KEY)


class BlockedIPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(EXEMPT):
            try:
                hit = match(client_ip(request))
            except Exception:  # noqa: BLE001 — falha no bloqueio nunca derruba o sistema
                logger.exception('Falha ao checar IP bloqueado')
                hit = None
            if hit:
                from audit.models import BlockedIP
                BlockedIP.objects.filter(network=hit).update(hits=F('hits') + 1, last_hit_at=timezone.now())
                return JsonResponse({'detail': 'Acesso bloqueado pela segurança do Cadrius.', 'code': 'ip_blocked'}, status=403)
        return self.get_response(request)
