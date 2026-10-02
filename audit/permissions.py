from rest_framework.permissions import BasePermission

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership


class IsOrganizationAdmin(BasePermission):
    """OWNER/ADMIN do escritório ativo (a trilha do escritório só é visível a quem o gere)."""

    message = 'Apenas donos ou administradores do escritório podem aceder à auditoria.'

    def has_permission(self, request, view):
        membership = get_active_membership(request.user)
        return bool(membership and membership.role in MANAGE_TEAM_ROLES)


class IsPlatformStaff(BasePermission):
    """Equipa de segurança do Cadrius (is_staff) — visão global (Security Center)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_staff)
