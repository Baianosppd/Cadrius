"""Regras de aceite/consentimento: quais documentos são exigidos e o que ainda está pendente."""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

from audit import service as audit
from audit.context import get_context
from privacy.models import ConsentRecord, LegalDocument

# Documentos exigidos de TODO utilizador para usar a plataforma.
REQUIRED_KINDS = (LegalDocument.Kind.TERMS, LegalDocument.Kind.PRIVACY, LegalDocument.Kind.CIENCIA)

_CACHE_TTL = 300


def acceptance_required() -> bool:
    return getattr(settings, 'LEGAL_ACCEPTANCE_REQUIRED', True)


def current_documents(kinds=None):
    qs = LegalDocument.objects.filter(is_current=True)
    return qs.filter(kind__in=kinds) if kinds else qs


def _cache_key(user_pk) -> str:
    return f'privacy:pending:{user_pk}'


def pending_documents(user) -> list[LegalDocument]:
    """Documentos obrigatórios vigentes que o utilizador ainda não aceitou (na versão vigente)."""
    if not acceptance_required() or not getattr(user, 'is_authenticated', False):
        return []
    required = list(current_documents(REQUIRED_KINDS))
    accepted_ids = set(
        ConsentRecord.objects.filter(user_ref=str(user.pk), granted=True, document__in=required)
        .values_list('document_id', flat=True)
    )
    return [d for d in required if d.pk not in accepted_ids]


def has_pending(user) -> bool:
    """Versão com cache curto (chamada em TODO pedido JWT)."""
    key = _cache_key(user.pk)
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = bool(pending_documents(user))
    cache.set(key, result, _CACHE_TTL)
    return result


def record_consent(user, document: LegalDocument, *, granted=True, purpose='essential', method='checkbox',
                   organization=None, legal_basis=None) -> ConsentRecord:
    ctx = get_context()
    record = ConsentRecord.objects.create(
        user=user, user_ref=str(user.pk), organization_id=getattr(organization, 'pk', None),
        document=document, purpose=purpose, granted=granted, method=method,
        legal_basis=legal_basis or ('consentimento' if purpose != 'essential' else 'contrato'),
        ip=ctx.ip, user_agent_hash=ctx.user_agent_hash,
    )
    cache.delete(_cache_key(user.pk))
    audit.log('consent.granted' if granted else 'consent.revoked', actor=user, target=document,
              changes={'purpose': purpose, 'version': document.version, 'evidence_sha256': document.content_sha256[:16]},
              data_categories=['identificacao'], legal_basis=record.legal_basis)
    return record
