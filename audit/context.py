"""Contexto da requisição (request_id, IP, ator, escritório) propagado por contextvars.

Permite que qualquer código — incluindo signals, views DRF e tarefas Django-Q — registe eventos
já correlacionados, sem passar o ``request`` por todas as funções.
"""
from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field, replace

from audit.redaction import mask_email, stable_hash


@dataclass(frozen=True)
class AuditContext:
    request_id: str = ''
    ip: str | None = None
    user_agent_hash: str = ''
    actor_type: str = 'anonymous'
    actor_id: str = ''
    actor_label: str = ''
    organization_id: str | None = None
    auth_method: str = ''
    extra: dict = field(default_factory=dict)


_current: contextvars.ContextVar[AuditContext] = contextvars.ContextVar('audit_context', default=AuditContext())


def get_context() -> AuditContext:
    return _current.get()


def set_context(ctx: AuditContext):
    return _current.set(ctx)


def reset_context(token) -> None:
    _current.reset(token)


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_actor(user, organization=None, auth_method: str = '') -> None:
    """Associa o utilizador (e escritório) ao contexto atual — chamado após autenticar (JWT/sessão)."""
    ctx = get_context()
    if user is None or not getattr(user, 'is_authenticated', False):
        return
    actor_type = 'admin' if getattr(user, 'is_staff', False) else 'user'
    _current.set(replace(
        ctx,
        actor_type=actor_type,
        actor_id=str(user.pk),
        actor_label=mask_email(getattr(user, 'email', '') or ''),
        organization_id=str(organization.pk) if organization is not None else ctx.organization_id,
        auth_method=auth_method or ctx.auth_method,
    ))


def client_ip(request) -> str | None:
    """IP do cliente atrás do Traefik. O 1º item do X-Forwarded-For é escrito pelo próprio cliente (falsificável); o confiável é
    o que o NOSSO proxy acrescentou: o N-ésimo a partir do fim, com N = AXES_PROXY_COUNT (1 = só o Traefik). CAD-221."""
    from django.conf import settings
    forwarded = [p.strip() for p in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if p.strip()]
    count = int(getattr(settings, 'AXES_IPWARE_PROXY_COUNT', 1) or 0)
    if forwarded and count > 0:
        return forwarded[-count] if len(forwarded) >= count else forwarded[0]
    return request.META.get('REMOTE_ADDR') or None


def context_from_request(request) -> AuditContext:
    ua = request.META.get('HTTP_USER_AGENT', '')
    return AuditContext(
        request_id=(request.META.get('HTTP_X_REQUEST_ID') or new_request_id())[:64],
        ip=client_ip(request),
        user_agent_hash=stable_hash(ua)[:16] if ua else '',
    )
