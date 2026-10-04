"""Clipping de notícias jurídicas de fontes PÚBLICAS configuradas (RSS). Só busca URLs da lista ``NEWS_FEEDS`` (definida pela equipe, nunca pelo usuário)."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
import xml.etree.ElementTree as ET  # nosec B405 — feeds de fontes configuradas pela equipe, com tamanho limitado (defusedxml não é necessário aqui)
from email.utils import parsedate_to_datetime

import requests
from django.conf import settings
from django.utils import timezone

from integrations.ssrf import UnsafeURLError, validate_outbound_url
from research.models import NewsItem

logger = logging.getLogger(__name__)
MAX_BYTES = 2_000_000
TAG = re.compile(r'<[^>]+>')


def _text(node, tag):
    el = node.find(tag)
    return ''.join(el.itertext()).strip() if el is not None else ''


def parse_feed(xml_bytes: bytes):
    """Lê RSS 2.0 (``item``) e Atom (``entry``). Devolve [{'title','url','summary','published_at'}]."""
    if b'<!DOCTYPE' in xml_bytes[:2000].upper() or b'<!ENTITY' in xml_bytes[:5000].upper():
        raise ValueError('Feed com DOCTYPE/ENTITY recusado.')   # evita expansão de entidades (billion laughs / XXE)
    root = ET.fromstring(xml_bytes)  # nosec B314
    items = []
    for node in list(root.iter('item')) + [e for e in root.iter() if e.tag.endswith('}entry')]:
        link = _text(node, 'link')
        if not link:                                              # Atom: <link href="..."/>
            el = next((c for c in node if c.tag.endswith('link')), None)
            link = el.get('href', '') if el is not None else ''
        published = _text(node, 'pubDate') or _text(node, '{http://www.w3.org/2005/Atom}updated')
        try:
            when = parsedate_to_datetime(published) if published else None
            if when is None and published:
                from datetime import datetime
                when = datetime.fromisoformat(published.replace('Z', '+00:00'))
        except (TypeError, ValueError):
            when = None
        summary = TAG.sub('', _text(node, 'description') or _text(node, '{http://www.w3.org/2005/Atom}summary'))
        title = TAG.sub('', _text(node, 'title') or _text(node, '{http://www.w3.org/2005/Atom}title'))
        if title and link.startswith(('http://', 'https://')):
            items.append({'title': title[:300], 'url': link[:500], 'summary': summary[:1000], 'published_at': when})
    return items


def refresh_feeds() -> dict:
    stats = {'feeds': 0, 'new': 0, 'errors': 0}
    for name, url in getattr(settings, 'NEWS_FEEDS', []) or []:
        stats['feeds'] += 1
        try:
            validate_outbound_url(url)
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'CadriusBot/1.0 (+https://cadrius.ia.br)'}, stream=True)
            body = resp.raw.read(MAX_BYTES + 1, decode_content=True)
            if resp.status_code != 200 or len(body) > MAX_BYTES:
                raise ValueError(f'resposta {resp.status_code} ou grande demais')
            for it in parse_feed(body):
                _, created = NewsItem.objects.get_or_create(url=it['url'], defaults={'source': name[:80], **{k: it[k] for k in ('title', 'summary', 'published_at')}})
                stats['new'] += int(created)
        except (requests.RequestException, UnsafeURLError, ValueError, ET.ParseError) as exc:
            stats['errors'] += 1
            logger.warning('Feed %s falhou: %s', name, exc.__class__.__name__)
    # retenção: notícias velhas não precisam ficar (dado público, mas sem acúmulo infinito)
    NewsItem.objects.filter(created_at__lt=timezone.now() - timedelta(days=180)).delete()
    return stats
