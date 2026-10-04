"""Embeddings locais (CAD-165). Sem dependência externa nem chamada de rede: *feature hashing* de palavras e bigramas em 384 dimensões.

É lexical (acha textos parecidos pelo vocabulário), suficiente para o piloto — "exemplo de leitura parecida" e "modelo de peça parecido".
A interface permite trocar por um modelo semântico (ex.: multilingual-e5-small via ONNX) sem mexer no resto: defina ``BRAIN_EMBEDDER``.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata

from django.conf import settings

DIM = 384
_STOP = frozenset('a o as os de da do das dos e em no na nos nas um uma para por com que se ao à ou foi ser é são'.split())


def _words(text: str):
    text = ''.join(c for c in unicodedata.normalize('NFD', (text or '').casefold()) if unicodedata.category(c) != 'Mn')
    return [w for w in re.findall(r'[a-z0-9]{3,}', text) if w not in _STOP]


def _bucket(token: str) -> tuple[int, int]:
    h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), 'big')
    return h % DIM, 1 if (h >> 63) & 1 else -1      # posição e sinal (reduz colisões)


def hashing_embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    words = _words(text)
    for token in words + [f'{a}_{b}' for a, b in zip(words, words[1:])]:
        i, sign = _bucket(token)
        vec[i] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 5) for v in vec]


def embed(text: str) -> list[float]:
    custom = getattr(settings, 'BRAIN_EMBEDDER', '')
    if custom:                                         # "pacote.modulo.funcao": texto -> lista de floats normalizada
        from django.utils.module_loading import import_string
        return import_string(custom)(text)
    return hashing_embed(text)


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))           # vetores já normalizados
