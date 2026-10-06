"""Dados públicos brasileiros sem chave (CAD-223) — BrasilAPI (https://brasilapi.com.br): CNPJ (Receita Federal) e CEP.

Endpoints fixos (sem URL vinda do usuário → sem risco de SSRF); respostas em cache; falha vira mensagem amigável.
"""
from __future__ import annotations

import requests
from django.core.cache import cache

BASE = 'https://brasilapi.com.br/api'
TIMEOUT = 8


class PublicDataError(Exception):
    pass


def _get(path: str, what: str) -> dict:
    try:
        resp = requests.get(f'{BASE}{path}', timeout=TIMEOUT, headers={'User-Agent': 'Cadrius'})
    except requests.RequestException as exc:
        raise PublicDataError(f'{what}: serviço público fora do ar. Preencha à mão.') from exc
    if resp.status_code == 404:
        raise PublicDataError(f'{what} não encontrado.')
    if resp.status_code != 200:
        raise PublicDataError(f'{what}: consulta indisponível agora (HTTP {resp.status_code}).')
    try:
        return resp.json()
    except ValueError as exc:
        raise PublicDataError(f'{what}: resposta inválida.') from exc


def cnpj(digits: str) -> dict:
    key = f'brasilapi:cnpj:{digits}'
    hit = cache.get(key)
    if hit:
        return hit
    d = _get(f'/cnpj/v1/{digits}', 'CNPJ')
    phone = ''.join(ch for ch in str(d.get('ddd_telefone_1') or '') if ch.isdigit())
    address = ', '.join(x for x in [str(d.get('descricao_tipo_de_logradouro') or '').strip() + ' ' + str(d.get('logradouro') or '').strip(),
                                    str(d.get('numero') or '').strip(), str(d.get('bairro') or '').strip()] if x.strip())
    out = {'cnpj': digits, 'razao_social': d.get('razao_social') or '', 'nome_fantasia': d.get('nome_fantasia') or '',
           'situacao': d.get('descricao_situacao_cadastral') or '', 'atividade': d.get('cnae_fiscal_descricao') or '',
           'endereco': address.strip(), 'municipio': d.get('municipio') or '', 'uf': d.get('uf') or '', 'cep': d.get('cep') or '',
           'telefone': phone if len(phone) in (10, 11) else '', 'email': (d.get('email') or '').lower(),
           'fonte': 'Receita Federal (via BrasilAPI)'}
    cache.set(key, out, 86400)
    return out


def cep(digits: str) -> dict:
    key = f'brasilapi:cep:{digits}'
    hit = cache.get(key)
    if hit:
        return hit
    d = _get(f'/cep/v2/{digits}', 'CEP')
    out = {'cep': digits, 'logradouro': d.get('street') or '', 'bairro': d.get('neighborhood') or '', 'cidade': d.get('city') or '',
           'uf': d.get('state') or ''}
    cache.set(key, out, 86400 * 7)
    return out
