"""Atalho para relógio, celular e voz (CAD-226).

Cada regra com o gatilho "Atalho" ganha um link secreto. Chamar o link (POST) dispara a regra na hora:
- Apple Watch / iPhone: app Atalhos → "Obter conteúdo de URL" (método POST) — dá para pôr na tela do relógio ou pedir à Siri;
- Android / Wear OS: app "HTTP Shortcuts" (ou Tasker) com um botão na tela do relógio;
- Alexa / Google Assistente / botões inteligentes: IFTTT ou Home Assistant chamando o webhook.

Segurança: a chave tem 256 bits e só aparece uma vez (o banco guarda o SHA-256). Gerar de novo invalida a anterior.
O atalho não manda nada para cliente (o gatilho não tem destinatário) e respeita o limite diário de execuções da regra.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

RATE_PER_MINUTE = 6


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def url_for(rule, key: str) -> str:
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/')
    return f'{base}/api/v1/publico/atalho/{rule.pk}/{key}/'


def rotate(rule) -> str:
    """Gera uma chave nova (a anterior deixa de valer) e devolve a URL completa — mostrada uma única vez."""
    key = secrets.token_urlsafe(32)
    rule.shortcut_key_hash = _hash(key)
    rule.save(update_fields=['shortcut_key_hash', 'updated_at'])
    return url_for(rule, key)


def check(rule, key: str) -> bool:
    return bool(rule.shortcut_key_hash) and hmac.compare_digest(rule.shortcut_key_hash, _hash(key or ''))


def throttled(rule) -> bool:
    k = f'atalho:{rule.pk}:{timezone.now():%Y%m%d%H%M}'
    n = cache.get_or_set(k, 0, 70)
    if n >= RATE_PER_MINUTE:
        return True
    try:
        cache.incr(k)
    except ValueError:
        cache.set(k, 1, 70)
    return False


def fire(rule, texto: str = '', origem: str = '') -> str:
    """Enfileira a execução e devolve a chave de deduplicação."""
    from core.queue import enqueue
    dedupe = f'atalho-{uuid.uuid4().hex}'
    refs = {'texto': (texto or '')[:500], 'origem': (origem or 'atalho')[:40],
            'quando': timezone.localtime().strftime('%d/%m/%Y %H:%M'), 'user_id': str(rule.created_by_id or '')}
    enqueue('automations.engine.execute', rule.pk, refs, dedupe)
    return dedupe
