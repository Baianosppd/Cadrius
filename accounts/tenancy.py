"""
Isolamento multi-tenant para a API REST.

Resolve o escritório ativo a partir de ``request.tenant`` (TenantMiddleware)
ou, em pedidos JWT (onde o middleware ainda vê AnonymousUser), via
``get_active_membership``.
"""
from __future__ import annotations

from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied

from accounts.team_roles import get_active_membership


def resolve_request_tenant(request):
    """
    Devolve a ``Organization`` ativa do pedido, ou ``None``.

    Preferência: ``request.tenant`` (middleware). Fallback: membership ativa
    do utilizador autenticado (necessário com JWT/DRF).
    """
    tenant = getattr(request, "tenant", None)
    if tenant is not None:
        return tenant

    user = getattr(request, "user", None)
    membership = get_active_membership(user)
    if membership is None:
        return None
    return membership.organization


class TenantQuerysetMixin:
    """
    Filtra querysets pelo escritório ativo e injeta ``organization`` no create.

    Subclasses sem FK ``organization`` devem sobrescrever
    ``filter_queryset_by_tenant`` e/ou ``get_perform_create_kwargs``.
    """

    tenant_field = "organization"
    require_tenant_on_create = True

    def get_tenant(self):
        return resolve_request_tenant(self.request)

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset.none()
        return self.filter_queryset_by_tenant(queryset)

    def filter_queryset_by_tenant(self, queryset):
        tenant = self.get_tenant()
        if tenant is None:
            return queryset.none()
        return queryset.filter(**{self.tenant_field: tenant})

    def get_perform_create_kwargs(self):
        """Kwargs passados a ``serializer.save(...)`` no create."""
        if not self.require_tenant_on_create:
            return {}
        tenant = self.get_tenant()
        if tenant is None:
            raise PermissionDenied(
                detail=(
                    "Não há um escritório ativo associado à sua conta. "
                    "Peça acesso a um escritório para criar este registo."
                ),
                code="no_organization",
            )
        return {self.tenant_field: tenant}

    def perform_create(self, serializer):
        serializer.save(**self.get_perform_create_kwargs())


class TenantAwareViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """ModelViewSet com isolamento automático por ``request.tenant``."""


class TenantAwareGenericViewSet(TenantQuerysetMixin, viewsets.GenericViewSet):
    """GenericViewSet com o mesmo isolamento (list/retrieve/mixins livres)."""
