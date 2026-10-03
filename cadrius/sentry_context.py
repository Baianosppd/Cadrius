"""Contexto de utilizador/escritório para o Sentry (CAD-056).

Cada erro registado no painel indica o ID do utilizador e o ID da Organization
(escritório) afetados. Só se enviam identificadores — nunca e-mail ou nome.
"""
from __future__ import annotations

import sentry_sdk


def set_sentry_context(user=None, organization=None) -> None:
    """Associa utilizador e organização ao scope atual do Sentry."""
    if user is not None and getattr(user, 'is_authenticated', False):
        sentry_sdk.set_user({'id': str(user.pk)})
    if organization is not None:
        sentry_sdk.set_tag('organization_id', str(organization.pk))
        sentry_sdk.set_context('organization', {'id': str(organization.pk)})
