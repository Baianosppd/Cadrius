"""Número único do CNJ (Res. 65/2008): NNNNNNN-DD.AAAA.J.TR.OOOO — validação, formatação e tribunal de origem."""
from __future__ import annotations

import re

_FORMATTED = re.compile(r'^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$')

# Justiça estadual (J=8): TR → UF  ·  alias do índice na API pública do DataJud: "tj<uf>" (ex.: tjsp)
UF_BY_TR = {1: 'ac', 2: 'al', 3: 'ap', 4: 'am', 5: 'ba', 6: 'ce', 7: 'dft', 8: 'es', 9: 'go', 10: 'ma', 11: 'mt', 12: 'ms', 13: 'mg',
            14: 'pa', 15: 'pb', 16: 'pr', 17: 'pe', 18: 'pi', 19: 'rj', 20: 'rn', 21: 'rs', 22: 'ro', 23: 'rr', 24: 'sc', 25: 'se',
            26: 'sp', 27: 'to'}


def digits(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def check_digits(seq: str, year: str, j: str, tr: str, origin: str) -> str:
    """DD = 98 − ((NNNNNNN AAAA J TR OOOO 00) mod 97)."""
    n = int(f'{seq}{year}{j}{tr}{origin}00')
    return f'{98 - (n % 97):02d}'


def parse(value: str):
    """Aceita com ou sem pontuação. Devolve dict ou None se inválido (formato ou dígito verificador)."""
    d = digits(value)
    if len(d) != 20:
        return None
    seq, dd, year, j, tr, origin = d[:7], d[7:9], d[9:13], d[13], d[14:16], d[16:]
    if check_digits(seq, year, j, tr, origin) != dd:
        return None
    return {'seq': seq, 'dd': dd, 'year': year, 'j': int(j), 'tr': int(tr), 'origin': origin,
            'formatted': f'{seq}-{dd}.{year}.{j}.{tr}.{origin}', 'digits': d}


def tribunal_alias(parsed: dict):
    """Alias do tribunal na API pública do DataJud ("tjsp", "trf1", "trt2"…) ou None se o ramo não é suportado/conhecido."""
    j, tr = parsed['j'], parsed['tr']
    if j == 8:
        uf = UF_BY_TR.get(tr)
        return f'tj{uf}' if uf else None
    if j == 4 and 1 <= tr <= 6:
        return f'trf{tr}'
    if j == 5 and 1 <= tr <= 24:
        return f'trt{tr}'
    if j == 3 and tr == 0:
        return 'stj'
    if j == 5 and tr == 0:
        return 'tst'
    return None
