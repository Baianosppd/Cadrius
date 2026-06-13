"""Mapeamento de cargos entre frontend e OrganizationMembership."""
from __future__ import annotations

from accounts.models import OrganizationMembership

FRONTEND_TO_BACKEND_ROLE = {
    'owner': 'OWNER',
    'dono': 'OWNER',
    'administrador': 'ADMIN',
    'admin': 'ADMIN',
    'advogado_pleno': 'MEMBER',
    'advogado_junior': 'MEMBER',
    'advogado': 'MEMBER',
    'membro': 'MEMBER',
    'viewer': 'VIEWER',
    'leitura': 'VIEWER',
    'OWNER': 'OWNER',
    'ADMIN': 'ADMIN',
    'MEMBER': 'MEMBER',
    'VIEWER': 'VIEWER',
}

BACKEND_TO_FRONTEND_ROLE = {
    'OWNER': 'owner',
    'ADMIN': 'administrador',
    'MEMBER': 'advogado_pleno',
    'VIEWER': 'viewer',
}

MANAGE_TEAM_ROLES = {'OWNER', 'ADMIN'}


def resolve_backend_role(value: str) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    lookup = normalized if normalized in FRONTEND_TO_BACKEND_ROLE else normalized.lower()
    return FRONTEND_TO_BACKEND_ROLE.get(lookup)


def role_to_frontend(role: str) -> str:
    return BACKEND_TO_FRONTEND_ROLE.get(role, role.lower())


def get_active_membership(user, *, organization=None):
    if user is None or not getattr(user, 'is_authenticated', False):
        return None

    queryset = user.memberships.filter(is_active=True).select_related('organization', 'organization__plan')
    if organization is not None:
        queryset = queryset.filter(organization=organization)
    return queryset.first()
