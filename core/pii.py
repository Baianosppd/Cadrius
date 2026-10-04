"""Proteção de dados pessoais em repouso (CAD-152): índices cegos (busca exata) e índices de tokens (busca parcial).

Os valores ficam cifrados (``core.utils.EncryptedTextField``, Fernet). Cifra é aleatória, então o banco não consegue
comparar nem buscar nela; para isso guardamos AO LADO um derivado que não revela o valor:

* **índice cego** (``blind_index``) — ``HMAC-SHA256(chave_do_índice, finalidade + valor normalizado)``: permite
  ``WHERE cpf_bidx = ...`` e **unicidade** (CPF/CNPJ) sem decifrar nada;
* **índice de tokens** (``search_tokens``) — HMAC de trigramas e prefixos das palavras: permite **busca parcial por nome**
  ("silv" acha "Maria da Silva") sem guardar o nome em claro. Quem vê o banco enxerga apenas hashes.

Limites conhecidos (aceitos): o índice revela *igualdade* (dois registros com o mesmo CPF têm o mesmo hash) e, no de tokens,
a frequência de trigramas; por isso a chave do índice é separada da chave de cifra e a finalidade entra no HMAC.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

TOKEN_LEN = 12  # hex chars por token (48 bits): colisões raras e índice compacto


def _key() -> bytes:
    raw = (getattr(settings, 'BLIND_INDEX_KEY', '') or '').strip()
    if raw:
        return raw.encode()
    if getattr(settings, 'ENCRYPTION_ALLOW_DERIVED_KEY', False):  # só DEBUG/testes
        return hashlib.sha256(b'cadrius-blind-index:' + settings.SECRET_KEY.encode()).digest()
    raise ImproperlyConfigured('BLIND_INDEX_KEY é obrigatória em produção (índices de busca dos dados pessoais cifrados).')


def strip_accents(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def normalize(value, kind: str = 'text') -> str:
    value = '' if value is None else str(value)
    if kind == 'digits':
        return re.sub(r'\D', '', value)
    return re.sub(r'\s+', ' ', strip_accents(value).casefold()).strip()


def _hmac(purpose: str, data: str) -> str:
    return hmac.new(_key(), f'{purpose}\x00{data}'.encode(), hashlib.sha256).hexdigest()


def blind_index(purpose: str, value, kind: str = 'digits'):
    """Hash determinístico para igualdade/unicidade. ``None`` se o valor for vazio."""
    norm = normalize(value, kind)
    return _hmac(purpose, norm) if norm else None


def _grams(word: str):
    padded = f'^{word}$'
    for i in range(len(padded) - 2):  # trigramas com marcadores de início/fim ("^ma", "mar", "ari", "ria", "ia$")
        yield padded[i:i + 3]
    for n in (1, 2):  # prefixos curtos: permitem buscar com 1–2 letras ("m", "ma")
        if len(word) >= n:
            yield f'^{word[:n]}'


def _token(purpose: str, gram: str) -> str:
    return _hmac(purpose, f'tok:{gram}')[:TOKEN_LEN]


def search_tokens(purpose: str, value) -> str:
    """Texto ``' tok1 tok2 ... '`` (com espaços nas pontas) para gravar na coluna ``*_idx``. Vazio se não houver palavras."""
    toks = {_token(purpose, g) for w in normalize(value).split() for g in _grams(w)}
    return f" {' '.join(sorted(toks))} " if toks else ''


def query_tokens(purpose: str, term) -> list[str]:
    """Tokens que TODOS precisam estar no índice para o registro casar com ``term`` (busca por palavras, parcial)."""
    out = set()
    for word in normalize(term).split():
        if len(word) >= 3:  # palavra completa/parcial ≥ 3 letras: trigramas do miolo (sem o marcador de fim)
            out.update(_token(purpose, g) for g in _grams_query(word))
        else:
            out.add(_token(purpose, f'^{word}'))
    return sorted(out)


def _grams_query(word: str):
    # Trecho digitado pode estar no meio da palavra: só trigramas "internos" (sem ^ ou $), mais o prefixo se for início.
    for i in range(len(word) - 2):
        yield word[i:i + 3]


def filter_by_term(queryset, field: str, purpose: str, term):
    """Restringe ``queryset`` aos registros cujo índice ``field`` contém todos os tokens de ``term``."""
    for tok in query_tokens(purpose, term):
        queryset = queryset.filter(**{f'{field}__contains': f' {tok} '})
    return queryset


class PIIIndexMixin:
    """Mantém as colunas de índice sincronizadas com os campos cifrados em ``save()``.

    ``BLIND_INDEXES = {'cpf': ('cpf_bidx', 'user.cpf', 'digits')}``      campo → (coluna, finalidade, tipo)
    ``TOKEN_INDEXES = {('first_name', 'last_name'): ('name_idx', 'user.name')}``   campos → (coluna, finalidade)
    Atualizações em massa (``QuerySet.update``) NÃO passam por aqui: use ``manage.py encrypt_pii`` depois.
    """

    BLIND_INDEXES: dict = {}
    TOKEN_INDEXES: dict = {}

    def sync_pii_indexes(self):
        touched = []
        for field, (column, purpose, kind) in self.BLIND_INDEXES.items():
            setattr(self, column, blind_index(purpose, getattr(self, field), kind))
            touched.append(column)
        for fields, (column, purpose) in self.TOKEN_INDEXES.items():
            text = ' '.join(str(getattr(self, f) or '') for f in fields)
            setattr(self, column, search_tokens(purpose, text))
            touched.append(column)
        return touched

    def save(self, *args, **kwargs):
        touched = self.sync_pii_indexes()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            source = set(self.BLIND_INDEXES) | {f for fs in self.TOKEN_INDEXES for f in fs}
            if source & set(update_fields):
                kwargs['update_fields'] = list(set(update_fields) | set(touched))
        super().save(*args, **kwargs)


# ----------------------------------------------------------------------------- auditoria e re-cifra (encrypt_pii / check de conformidade)
def encrypted_fields():
    """[(Model, [campos cifrados])] de TODAS as apps instaladas — descobre sozinho, sem lista manual para esquecer."""
    from django.apps import apps

    from core.utils import EncryptedJSONField, EncryptedTextField

    found = []
    for model in apps.get_models():
        fields = [f for f in model._meta.concrete_fields if isinstance(f, (EncryptedTextField, EncryptedJSONField))]
        if fields:
            found.append((model, fields))
    return found


def plaintext_counts():
    """{'tabela.coluna': linhas com valor NÃO cifrado} lendo o valor CRU do banco (sem passar pela decifra do ORM)."""
    from django.db import connection

    from core.utils import ENC_PREFIX

    counts = {}
    with connection.cursor() as cur:
        q = connection.ops.quote_name
        for model, fields in encrypted_fields():
            for f in fields:
                table, col = q(model._meta.db_table), q(f.column)
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} <> '' AND {col} NOT LIKE %s",
                            [ENC_PREFIX + '%'])
                counts[f'{model._meta.db_table}.{f.column}'] = cur.fetchone()[0]
    return counts
