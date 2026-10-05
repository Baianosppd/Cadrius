"""DJEN — Diário de Justiça Eletrônico Nacional (CNJ), API pública de comunicações processuais ("Comunica").

``GET {DJEN_API_URL}?numeroOab=&ufOab=&dataDisponibilizacaoInicio=&dataDisponibilizacaoFim=&pagina=&itensPorPagina=``
sem autenticação; 5 ou 100 itens por página; até 10.000 resultados por busca; limite de requisições informado em ``x-ratelimit-*``.
**[VALIDAR]** formato das datas (usamos AAAA-MM-DD), nomes dos campos e termos de uso no Swagger oficial
(comunicaapi.pje.jus.br/swagger) antes de ligar em produção — o parser aceita as duas grafias conhecidas dos campos.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime

import requests
from django.conf import settings

from research.providers.datajud import ProviderError

TIMEOUT = 20
PAGE_SIZE = 100
MAX_PAGES = 5
MAX_TEXT = 50_000
_TAGS = re.compile(r'<[^>]+>')
_SPACES = re.compile(r'[ \t\r\f\v]+')


def clean_text(raw) -> str:
    """Teor em HTML → texto simples (quebras de parágrafo preservadas)."""
    text = re.sub(r'(?i)<\s*(br|/p|/div|/li)\s*/?>', '\n', str(raw or ''))
    text = html.unescape(_TAGS.sub('', text))
    lines = [_SPACES.sub(' ', ln).strip() for ln in text.split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()[:MAX_TEXT]


def _date(value):
    if not value:
        return None
    s = str(value)[:10]
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _cnj(item) -> str:
    masked = item.get('numeroprocessocommascara') or item.get('numeroProcessoComMascara')
    if masked:
        return str(masked)
    digits = re.sub(r'\D', '', str(item.get('numero_processo') or item.get('numeroProcesso') or ''))
    if len(digits) == 20:
        return f'{digits[:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:]}'
    return digits


def normalize(item: dict) -> dict | None:
    ext = item.get('id') or item.get('hash')
    day = _date(item.get('data_disponibilizacao') or item.get('dataDisponibilizacao') or item.get('datadisponibilizacao'))
    if not ext or not day:
        return None
    partes = [{'nome': str(d.get('nome') or '')[:200], 'polo': str(d.get('polo') or '')[:2]}
              for d in item.get('destinatarios') or [] if isinstance(d, dict) and d.get('nome')]
    link = str(item.get('link') or '')
    return {
        'external_id': str(ext)[:64], 'tribunal': str(item.get('siglaTribunal') or '')[:20],
        'tipo': str(item.get('tipoComunicacao') or '')[:80], 'orgao': str(item.get('nomeOrgao') or '')[:255],
        'classe': str(item.get('nomeClasse') or '')[:255], 'cnj': _cnj(item), 'texto': clean_text(item.get('texto')),
        'partes': partes[:30], 'link': link[:500] if link.startswith('https://') else '', 'disponibilizada_em': day,
    }


def search(numero: str, uf: str, start: date, end: date) -> list[dict]:
    """Comunicações da OAB no período (todas as páginas, até MAX_PAGES). Levanta ProviderError."""
    base = getattr(settings, 'DJEN_API_URL', 'https://comunicaapi.pje.jus.br/api/v1/comunicacao')
    out = []
    for page in range(1, MAX_PAGES + 1):
        params = {'numeroOab': numero, 'ufOab': uf.upper(), 'dataDisponibilizacaoInicio': start.isoformat(),
                  'dataDisponibilizacaoFim': end.isoformat(), 'pagina': page, 'itensPorPagina': PAGE_SIZE}
        try:
            resp = requests.get(base, params=params, headers={'Accept': 'application/json'}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ProviderError(f'DJEN inacessível ({exc.__class__.__name__}).') from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(f'DJEN indisponível ou limite de consultas ({resp.status_code}). Tentaremos de novo.')
        if resp.status_code != 200:
            raise ProviderError(f'DJEN respondeu {resp.status_code}.', retryable=False)
        try:
            body = resp.json()
        except ValueError as exc:
            raise ProviderError('Resposta do DJEN não é JSON.', retryable=False) from exc
        items = body.get('items') or []
        out.extend(n for n in (normalize(i) for i in items if isinstance(i, dict)) if n)
        total = int(body.get('count') or 0)
        if len(items) < PAGE_SIZE or page * PAGE_SIZE >= total:
            break
    return out
