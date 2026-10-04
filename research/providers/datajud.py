"""DataJud (CNJ) — API pública de movimentações de processos. **[VALIDAR]** formato/chave/cobertura na documentação vigente do CNJ antes de ir a produção.

Endpoint por tribunal: ``POST {DATAJUD_BASE_URL}/api_publica_{alias}/_search`` (Elasticsearch) com ``Authorization: APIKey {DATAJUD_API_KEY}``.
A chave pública é divulgada pelo CNJ e pode mudar: por isso é configuração (``DATAJUD_API_KEY``), nunca código. Traz metadados e movimentações, não o inteiro teor.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone as dt_tz

import requests
from django.conf import settings

TIMEOUT = 20


class ProviderError(Exception):
    """Falha ao consultar a fonte (rede, chave, limite). ``retryable`` indica se vale tentar de novo depois."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=dt_tz.utc)
    except ValueError:
        return None


def search_case(cnj_digits: str, tribunal: str) -> dict | None:
    """Devolve {'classe': str, 'orgao': str, 'movements': [{'occurred_at', 'code', 'name', 'complement', 'digest'}]} ou None se não achar."""
    key = (getattr(settings, 'DATAJUD_API_KEY', '') or '').strip()
    if not key:
        raise ProviderError('DATAJUD_API_KEY não configurada.', retryable=False)
    base = getattr(settings, 'DATAJUD_BASE_URL', 'https://api-publica.datajud.cnj.jus.br').rstrip('/')
    try:
        resp = requests.post(f'{base}/api_publica_{tribunal}/_search', json={'query': {'match': {'numeroProcesso': cnj_digits}}},
                             headers={'Authorization': f'APIKey {key}', 'Content-Type': 'application/json'}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderError(f'DataJud inacessível ({exc.__class__.__name__}).') from exc
    if resp.status_code in (401, 403):
        raise ProviderError('DataJud recusou a chave (401/403).', retryable=False)
    if resp.status_code == 429 or resp.status_code >= 500:
        raise ProviderError(f'DataJud indisponível ({resp.status_code}).')
    if resp.status_code != 200:
        raise ProviderError(f'DataJud respondeu {resp.status_code}.', retryable=False)
    hits = (resp.json().get('hits') or {}).get('hits') or []
    if not hits:
        return None
    src = hits[0].get('_source') or {}
    movements = []
    for m in src.get('movimentos') or []:
        occurred = _parse_dt(m.get('dataHora'))
        code, name = str(m.get('codigo') or ''), str(m.get('nome') or '')[:255]
        complement = '; '.join(str(c.get('nome') or c.get('descricao') or '') for c in (m.get('complementosTabelados') or []))[:500]
        digest = hashlib.sha1(f'{occurred.isoformat() if occurred else ""}|{code}|{name}|{complement}'.encode()).hexdigest()  # nosec B324
        movements.append({'occurred_at': occurred, 'code': code, 'name': name, 'complement': complement, 'digest': digest})
    return {'classe': (src.get('classe') or {}).get('nome', ''), 'orgao': (src.get('orgaoJulgador') or {}).get('nome', ''), 'movements': movements}
