"""Áreas da equipe Cadrius (CAD-168). Acesso = conta ativa + ``is_staff`` + (superusuário OU grupo da área).

Grupos: "Cadrius TI" (saúde do sistema, usuários, segurança) e "Cadrius Financeiro" (preços, promoções, créditos, assinaturas).
Atribuir: ``manage.py cadrius_staff email@... --areas ti,financeiro``.
"""
from rest_framework import permissions

AREA_GROUPS = {'ti': 'Cadrius TI', 'financeiro': 'Cadrius Financeiro'}


def user_areas(user) -> list[str]:
    if not (user and user.is_authenticated and user.is_active and user.is_staff):
        return []
    if user.is_superuser:
        return sorted(AREA_GROUPS)
    names = set(user.groups.values_list('name', flat=True))
    return sorted(a for a, g in AREA_GROUPS.items() if g in names)


class HasArea(permissions.BasePermission):
    """Use ``HasArea.of('ti')``. Sem área → 403 (e o middleware de auditoria registra o acesso negado)."""

    @classmethod
    def of(cls, *areas):
        return type(f'HasArea_{"_".join(areas)}', (cls,), {'areas': areas})

    areas: tuple = ()

    def has_permission(self, request, view):
        mine = user_areas(request.user)
        return any(a in mine for a in self.areas) if self.areas else bool(mine)


IsBackoffice = HasArea.of()            # qualquer área
IsTI = HasArea.of('ti')
IsFinanceiro = HasArea.of('financeiro')
