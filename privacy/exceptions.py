from rest_framework import status
from rest_framework.exceptions import APIException


class ConsentRequired(APIException):
    """428 Precondition Required: o utilizador precisa aceitar versões vigentes dos documentos legais."""

    status_code = status.HTTP_428_PRECONDITION_REQUIRED
    default_code = 'consent_required'
    default_detail = 'É necessário aceitar os termos vigentes para continuar.'

    def __init__(self, pending=()):
        super().__init__(detail={
            'detail': self.default_detail,
            'code': self.default_code,
            'pending': [{'id': d.pk, 'kind': d.kind, 'version': d.version, 'title': d.title} for d in pending],
        })
