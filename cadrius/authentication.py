from rest_framework_simplejwt.authentication import JWTAuthentication

from accounts.team_roles import get_active_membership
from cadrius.sentry_context import set_sentry_context


class SentryJWTAuthentication(JWTAuthentication):
    """
    JWTAuthentication que, após autenticar, anexa utilizador e organização ao Sentry.

    Necessário porque o JWT é resolvido ao nível da view (DRF), depois dos middlewares:
    o ``TenantMiddleware`` ainda vê um utilizador anónimo nos pedidos da API.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _token = result
            membership = get_active_membership(user)
            set_sentry_context(user, membership.organization if membership else None)
        return result
