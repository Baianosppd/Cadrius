from rest_framework_simplejwt.authentication import JWTAuthentication

from accounts.team_roles import get_active_membership
from audit.context import bind_actor
from privacy import consent
from privacy.exceptions import ConsentRequired
from rest_framework.exceptions import PermissionDenied
from cadrius.sentry_context import set_sentry_context


# Rotas acessíveis MESMO com aceite pendente (o utilizador precisa conseguir ver/aceitar os termos,
# sair da conta e exercer direitos de titular).
CONSENT_EXEMPT_PREFIXES = ('/api/v1/legal/', '/api/v1/auth/', '/api/v1/privacy/', '/api/billing/plans')
# Com senha temporária (CAD-221) só o necessário para trocá-la: perfil, troca de senha, MFA e sair.
PASSWORD_CHANGE_EXEMPT_PREFIXES = ('/api/v1/auth/',)


class PasswordChangeRequired(PermissionDenied):
    default_detail = 'Troque a senha temporária para continuar.'
    default_code = 'password_change_required'


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
            organization = membership.organization if membership else None
            set_sentry_context(user, organization)
            bind_actor(user, organization, auth_method='jwt')
            path = getattr(request, 'path', '')
            if getattr(user, 'must_change_password', False) and not path.startswith(PASSWORD_CHANGE_EXEMPT_PREFIXES):
                raise PasswordChangeRequired()
            if not path.startswith(CONSENT_EXEMPT_PREFIXES) and consent.has_pending(user):
                # LGPD: sem aceite da versão vigente não há acesso a dados (428 + lista do que falta).
                raise ConsentRequired(consent.pending_documents(user))
        return result
