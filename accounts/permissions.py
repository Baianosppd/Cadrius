"""Permissões por cargo (RBAC — RF-007). Antes o cargo só controlava convites; VIEWER podia alterar tudo."""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership

WRITE_ROLES = {'OWNER', 'ADMIN', 'MEMBER'}


class OrgRolePermission(BasePermission):
    """
    - Leitura: qualquer membro ativo (inclui VIEWER).
    - Escrita (POST/PUT/PATCH/DELETE): OWNER, ADMIN ou MEMBER; VIEWER recebe 403.
    Utilizadores sem escritório mantêm o comportamento anterior (o isolamento por tenant já os limita).
    """

    message = 'O seu cargo (somente leitura) não permite alterar este recurso.'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        membership = get_active_membership(request.user)
        return membership is None or membership.role in WRITE_ROLES


class IsOrgManager(BasePermission):
    """Apenas OWNER/ADMIN do escritório (aprovações, políticas, configurações sensíveis)."""

    message = 'Apenas donos ou administradores do escritório podem executar esta ação.'

    def has_permission(self, request, view):
        membership = get_active_membership(request.user) if request.user.is_authenticated else None
        return bool(membership and membership.role in MANAGE_TEAM_ROLES)
