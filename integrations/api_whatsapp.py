"""API do WhatsApp hospedado pelo Cadrius (CAD-225). Prefixo: /api/v1/integrations/whatsapp/ e público /api/v1/publico/whatsapp/."""
from django.conf import settings
from django.core.cache import cache
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organization
from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from integrations import whatsapp_hosted as wa


def _manager(request):
    m = get_active_membership(request.user)
    if m is None or m.role not in MANAGE_TEAM_ROLES:
        return None, Response({'detail': 'Apenas donos ou administradores conectam o WhatsApp do escritório.'},
                              status=status.HTTP_403_FORBIDDEN)
    return m, None


def _status_payload(org, user):
    st = wa.state(org)
    if st == 'open':
        wa.ensure_connection(org, user)
    return {'disponivel': True, 'estado': st, 'conectado': st == 'open'}


class WhatsAppStatusView(APIView):
    """GET — o Cadrius hospeda o WhatsApp neste ambiente? E o do escritório está conectado?"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        if not wa.available():
            return Response({'disponivel': False, 'estado': None, 'conectado': False})
        try:
            return Response(_status_payload(m.organization, request.user))
        except wa.WhatsAppError as exc:
            return Response({'disponivel': False, 'estado': None, 'conectado': False, 'detail': str(exc)})


class WhatsAppConnectView(APIView):
    """POST {numero} — prepara a conexão e devolve QR code + código de pareamento."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        m, err = _manager(request)
        if err:
            return err
        try:
            data = wa.start(m.organization, request.data.get('numero', ''))
        except wa.WhatsAppError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if data.get('estado') == 'open':
            wa.ensure_connection(m.organization, request.user)
        audit.log('connection.updated', actor=request.user, organization=m.organization,
                  changes={'provider': 'whatsapp', 'action': 'pairing_started'})
        return Response(data)


class WhatsAppLinkView(APIView):
    """POST {numero} — link (15 min) para quem está com o celular do escritório concluir a conexão sem login."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        m, err = _manager(request)
        if err:
            return err
        try:
            token = wa.make_link_token(m.organization, request.data.get('numero', ''), request.user)
        except wa.WhatsAppError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        audit.log('connection.updated', actor=request.user, organization=m.organization,
                  changes={'provider': 'whatsapp', 'action': 'pairing_link_created'})
        return Response({'link': f'{settings.FRONTEND_URL}/whatsapp/{token}', 'expira_em_minutos': wa.LINK_MAX_AGE // 60})


class WhatsAppDisconnectView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        m, err = _manager(request)
        if err:
            return err
        try:
            wa.disconnect(m.organization)
        except wa.WhatsAppError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        wa.deactivate_connection(m.organization)
        audit.log('connection.deleted', actor=request.user, organization=m.organization, changes={'provider': 'whatsapp'})
        return Response(status=status.HTTP_204_NO_CONTENT)


class WhatsAppPublicPairView(APIView):
    """GET /api/v1/publico/whatsapp/<token>/ — sem login: código de pareamento para quem está com o celular (link de 15 min)."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        try:
            data = wa.read_link_token(token)
        except wa.WhatsAppError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        org = Organization.objects.filter(pk=data['o']).first()
        if org is None:
            return Response({'detail': 'Link inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.filter(pk=data['u'], is_active=True).first()
        try:
            st = wa.state(org)
            if st == 'open':
                if user:
                    wa.ensure_connection(org, user)
                return Response({'escritorio': org.name, 'estado': 'open'})
            key = f'wa:pair:{token[-32:]}'
            cached = cache.get(key)              # a página consulta a cada poucos segundos: não gera código novo a cada vez
            if cached is None:
                cached = wa.start(org, data['n'])
                cache.set(key, cached, 40)
        except wa.WhatsAppError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'escritorio': org.name, 'estado': cached.get('estado'), 'codigo_pareamento': cached.get('codigo_pareamento', ''),
                         'numero_final': cached.get('numero_final', '')})
