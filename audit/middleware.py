from __future__ import annotations

import re

from audit import service
from audit.context import bind_actor, context_from_request, reset_context, set_context

# /admin/<app>/<model>/...  (acesso de staff a dados dos clientes — RNE-012 / ISO 27001 A.8.15)
_ADMIN_MODEL_RE = re.compile(r'^/admin/(?P<app>[\w-]+)/(?P<model>[\w-]+)/')
_ADMIN_SKIP_APPS = {'jsi18n', 'login', 'logout', 'password_change'}


class AuditContextMiddleware:
    """
    Cria o contexto de auditoria (request_id, IP, hash do user-agent), devolve ``X-Request-ID``
    e regista o acesso de staff ao Django Admin. Compatível com sync/async (Django 5).
    """

    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ctx = context_from_request(request)
        token = set_context(ctx)
        request.audit_request_id = ctx.request_id
        try:
            _tag_sentry(ctx.request_id)
            user = getattr(request, 'user', None)
            if user is not None and user.is_authenticated:  # sessão Django (admin)
                bind_actor(user, getattr(request, 'tenant', None), auth_method='session')

            response = self.get_response(request)
            response['X-Request-ID'] = ctx.request_id
            self._audit_admin_access(request, response)
            return response
        finally:
            reset_context(token)

    @staticmethod
    def _audit_admin_access(request, response):
        user = getattr(request, 'user', None)
        if not (user is not None and user.is_authenticated and user.is_staff):
            return
        match = _ADMIN_MODEL_RE.match(request.path)
        if not match or match.group('app') in _ADMIN_SKIP_APPS or request.method != 'GET':
            return
        if response.status_code == 200:
            service.log(
                'admin.access',
                reason=request.path[:255],
                target_type=f"{match.group('app')}.{match.group('model')}",
                data_categories=['administrativo'],
            )


def _tag_sentry(request_id: str) -> None:
    try:
        import sentry_sdk
        sentry_sdk.set_tag('request_id', request_id)
    except Exception:  # noqa: BLE001
        pass
