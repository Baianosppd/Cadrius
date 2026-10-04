"""Motor do conector: monta o pedido a partir da operação declarada, simula (dry-run) ou executa com salvaguardas.

Salvaguardas: caminho SEMPRE relativo à ``base_url`` (sem trocar de host), SSRF validado, sem redirecionamento, timeout e limite de
resposta; operação que ALTERA o ERP só roda ao vivo com ``live_enabled`` + confirmação humana explícita.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

import requests

from erp.presets import PRESETS
from integrations.ssrf import UnsafeURLError, validate_outbound_url

TIMEOUT = 20
MAX_BYTES = 1_000_000
PARAM = re.compile(r'\{(\w+)\}')
METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}


class ErpError(Exception):
    def __init__(self, message, code='erp_error'):
        super().__init__(message)
        self.code = code


def operations_of(connector) -> dict:
    ops = dict((PRESETS.get(connector.preset) or {}).get('operations', {}))
    ops.update(connector.operations or {})
    return ops


def validate_operation(name, spec):
    """Valida a definição (usada ao salvar). Levanta ErpError."""
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,59}', name or ''):
        raise ErpError(f'Nome de operação inválido: {name!r}.')
    if not isinstance(spec, dict) or spec.get('method', '').upper() not in METHODS:
        raise ErpError(f'{name}: método HTTP inválido.')
    path = spec.get('path', '')
    if not path.startswith('/') or path.startswith('//') or '://' in path or '..' in path or '\\' in path:
        raise ErpError(f'{name}: o caminho deve ser relativo à URL base (ex.: /v1/tarefas).')


def _resolve(value, data):
    if isinstance(value, str) and value.startswith('$.'):
        return data.get(value[2:])
    return value


def build_request(connector, operation: str, data: dict) -> dict:
    spec = operations_of(connector).get(operation)
    if spec is None:
        raise ErpError(f'Operação desconhecida: {operation}.', 'unknown_operation')
    validate_operation(operation, spec)
    missing = [k for k in spec.get('required', []) if data.get(k) in (None, '')]
    if missing:
        raise ErpError(f'Faltam campos: {", ".join(missing)}.', 'missing_fields')
    path = PARAM.sub(lambda m: quote(str(data.get(m.group(1), '')), safe=''), spec['path'])
    url = connector.base_url.rstrip('/') + path
    if urlsplit(url).netloc != urlsplit(connector.base_url).netloc:
        raise ErpError('O destino não pode sair do host configurado.', 'host_mismatch')
    query = {k: v for k, v in ((k, _resolve(v, data)) for k, v in (spec.get('query') or {}).items()) if v not in (None, '')}
    body = {k: v for k, v in ((k, _resolve(v, data)) for k, v in (spec.get('body') or {}).items()) if v is not None}
    return {'method': spec['method'].upper(), 'url': url, 'params': query, 'json': body or None,
            'mutating': bool(spec.get('mutating', spec['method'].upper() != 'GET'))}


def _auth_headers(connector) -> dict:
    auth = (PRESETS.get(connector.preset) or {}).get('auth', {'type': 'bearer'})
    token = (connector.credentials or {}).get('token', '')
    if not token:
        raise ErpError('Credencial (token) não configurada.', 'no_credentials')
    if auth.get('type') == 'header':
        return {auth.get('name', 'X-Api-Key'): token}
    return {'Authorization': f'Bearer {token}'}


def run(connector, operation: str, data: dict, *, dry_run: bool = True, confirmed: bool = False) -> dict:
    """Devolve {'dry_run', 'request': {...sem segredos}, 'status_code', 'response'}. Levanta ErpError."""
    req = build_request(connector, operation, data or {})
    preview = {k: req[k] for k in ('method', 'url', 'params', 'json')}
    if dry_run:
        return {'dry_run': True, 'request': preview, 'status_code': None, 'response': None}
    if not connector.live_enabled:
        raise ErpError('Execução real desligada neste conector (use a simulação ou ative-a).', 'live_disabled')
    if req['mutating'] and not confirmed:
        raise ErpError('Esta operação altera dados no ERP: requer confirmação humana.', 'needs_confirmation')
    try:
        validate_outbound_url(req['url'])
    except UnsafeURLError as exc:
        raise ErpError(f'Destino não permitido: {exc}', 'unsafe_url') from exc
    try:
        resp = requests.request(req['method'], req['url'], params=req['params'] or None, json=req['json'],
                                headers={**_auth_headers(connector), 'Accept': 'application/json'},
                                timeout=TIMEOUT, allow_redirects=False, stream=True)
        raw = resp.raw.read(MAX_BYTES + 1, decode_content=True)
    except requests.RequestException as exc:
        raise ErpError(f'ERP inacessível ({exc.__class__.__name__}).', 'unreachable') from exc
    if len(raw) > MAX_BYTES:
        raise ErpError('Resposta do ERP grande demais.', 'too_large')
    try:
        import json
        parsed = json.loads(raw.decode('utf-8')) if raw else None
    except ValueError:
        parsed = raw[:2000].decode('utf-8', 'replace')
    if 300 <= resp.status_code < 400:
        raise ErpError('O ERP respondeu com redirecionamento (não seguido).', 'redirect')
    return {'dry_run': False, 'request': preview, 'status_code': resp.status_code, 'response': parsed,
            'ok': 200 <= resp.status_code < 300}
