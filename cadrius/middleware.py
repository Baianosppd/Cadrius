from django.utils.deprecation import MiddlewareMixin


# Rotas sem isolamento de tenant (auth pública, webhooks, admin, health).
_SKIP_TENANT_PATH_PREFIXES = (
    "/admin",
    "/api/workflows/webhooks/catch",
    "/api/workflows/webhook/inbound",
    "/api/webhooks",
)

_SKIP_TENANT_PATH_EXACT = frozenset(
    {
        "/api/v1/auth/token",
        "/api/v1/auth/token/refresh",
        "/api/v1/auth/register",
        "/healthz",
    }
)


def _skip_tenant_path(path: str) -> bool:
    p = path.rstrip("/") or "/"
    if p in _SKIP_TENANT_PATH_EXACT:
        return True
    for prefix in _SKIP_TENANT_PATH_PREFIXES:
        if p == prefix or p.startswith(prefix + "/"):
            return True
    return False


class TenantMiddleware(MiddlewareMixin):
    """
    Middleware Multi-Tenant: define ``request.tenant`` a partir do utilizador autenticado,
    exceto em rotas públicas ou que não devem depender do escritório.
    """

    def process_request(self, request):
        if not hasattr(request, "user") or not request.user.is_authenticated:
            request.tenant = None
            return None

        if _skip_tenant_path(request.path):
            request.tenant = None
            return None

        request.tenant = request.user.organization
        return None
