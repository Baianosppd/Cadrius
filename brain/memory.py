"""Memória do escritório: guardar e recuperar o que é parecido (isolada por escritório). Ver brain/embeddings.py."""
from __future__ import annotations

from brain.embeddings import cosine, embed
from brain.models import MemoryItem

MAX_SCAN = 2000          # itens recentes avaliados por consulta (pgvector substitui isto quando habilitado — CAD-159)
MAX_TEXT = 4000


def remember(organization, kind, text, *, title='', payload=None, source='', user=None) -> MemoryItem:
    text = (text or '')[:MAX_TEXT]
    return MemoryItem.objects.create(
        organization=organization, kind=kind, title=title[:160], text=text, payload=payload or {}, source=source[:60],
        embedding=embed(f'{title}\n{text}'), created_by=user)


def similar(organization, query, *, kind=None, k=3, min_score=0.15):
    """Os ``k`` itens do PRÓPRIO escritório mais parecidos com ``query`` (nunca de outro escritório)."""
    qs = MemoryItem.objects.filter(organization=organization)
    if kind:
        qs = qs.filter(kind=kind)
    q = embed(query)
    scored = []
    for item in qs.order_by('-created_at')[:MAX_SCAN]:
        score = cosine(q, item.embedding) if item.embedding else 0.0
        if score >= min_score:
            scored.append((score, item))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [(round(s, 3), item) for s, item in scored[:k]]
