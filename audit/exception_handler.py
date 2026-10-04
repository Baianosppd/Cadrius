from rest_framework.views import exception_handler

from audit import service
from core.queue import RETRY_AFTER_SECONDS, QueueUnavailable


def audit_exception_handler(exc, context):
    """Handler DRF que regista permissões negadas (403) e limites de taxa (429)."""
    response = exception_handler(exc, context)
    if response is not None and isinstance(exc, QueueUnavailable):
        response['Retry-After'] = str(RETRY_AFTER_SECONDS)
    if response is not None and response.status_code in (403, 429):
        request = context.get('request')
        service.log(
            'ratelimit.hit' if response.status_code == 429 else 'permission.denied',
            outcome='denied',
            reason=f"{getattr(request, 'method', '')} {getattr(request, 'path', '')}"[:255],
        )
    return response
