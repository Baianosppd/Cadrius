"""Verificação da integridade da cadeia de hash."""
from __future__ import annotations

from audit.models import GENESIS_HASH, AuditCheckpoint, AuditEvent


def verify_chain(limit: int | None = None) -> dict:
    """
    Percorre a cadeia por ordem de ``seq`` e confirma, em cada evento, que
    ``prev_hash`` == hash do anterior e que ``hash`` == sha256(prev_hash + conteúdo).
    Devolve ``{'ok': bool, 'checked': n, 'first_bad_seq': int|None, 'reason': str}``.
    """
    checkpoint = AuditCheckpoint.objects.order_by('-purged_until_seq').first()
    expected_prev = checkpoint.last_hash if checkpoint else GENESIS_HASH
    checked = 0

    queryset = AuditEvent.objects.order_by('seq')
    if limit:
        queryset = queryset[:limit]
    for event in queryset.iterator(chunk_size=2000):
        if event.prev_hash != expected_prev:
            return {'ok': False, 'checked': checked, 'first_bad_seq': event.seq,
                    'reason': 'prev_hash não corresponde ao evento anterior (evento removido/inserido?)'}
        if event.compute_hash() != event.hash:
            return {'ok': False, 'checked': checked, 'first_bad_seq': event.seq,
                    'reason': 'conteúdo do evento foi alterado (hash não confere)'}
        expected_prev = event.hash
        checked += 1
    return {'ok': True, 'checked': checked, 'first_bad_seq': None, 'reason': ''}
