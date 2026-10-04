"""API do Google Calendar por escritório (CAD-162). Prefixo: /api/v1/integrations/google-calendar/"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect
from django.views import View
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from gcal import google_api as g
from gcal.models import GoogleCalendarApp, GoogleCalendarLink
from gcal.sync import pull_link

STATE_COOKIE = 'cadrius_gcal'
STATE_MAX_AGE = 600
SALT = 'cadrius.gcal'


def redirect_uri(request=None) -> str:
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/')
    if not base and request is not None:
        base = request.build_absolute_uri('/').rstrip('/')
    return f'{base}/api/v1/integrations/google-calendar/callback/'


class AppSerializer(serializers.Serializer):
    client_id = serializers.CharField(max_length=255)
    client_secret = serializers.CharField(max_length=255, required=False, allow_blank=True, write_only=True)
    enabled = serializers.BooleanField(required=False)
    share_details = serializers.BooleanField(required=False)
    event_minutes = serializers.IntegerField(required=False, min_value=5, max_value=480)

    def validate_client_id(self, value):
        value = value.strip()
        if not value.endswith('.apps.googleusercontent.com'):
            raise serializers.ValidationError('O ID do cliente do Google termina em ".apps.googleusercontent.com".')
        return value


def _membership(request):
    return get_active_membership(request.user)


class GCalStatusView(APIView):
    """GET — estado para a tela (o segredo nunca volta). Traz o redirect_uri que o escritório precisa cadastrar no Google Cloud."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        membership = _membership(request)
        if membership is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        app = GoogleCalendarApp.objects.filter(organization=membership.organization).first()
        link = GoogleCalendarLink.objects.filter(user=request.user).first()
        return Response({
            'app_configured': bool(app and app.enabled),
            'client_id': app.client_id if app else '',
            'share_details': app.share_details if app else True,
            'event_minutes': app.event_minutes if app else 30,
            'can_configure': membership.role in MANAGE_TEAM_ROLES,
            'connected': bool(link),
            'status': link.status if link else None,
            'last_sync_at': link.last_sync_at if link else None,
            'last_error': link.last_error if link else '',
            'redirect_uri': redirect_uri(request),
            'scope': g.SCOPE,
        })


class GCalAppView(APIView):
    """PUT/DELETE — dono/administrador cadastra as credenciais do PRÓPRIO app OAuth do Google do escritório."""
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request):
        membership = _membership(request)
        if membership is None or membership.role not in MANAGE_TEAM_ROLES:
            return Response({'detail': 'Apenas donos ou administradores.'}, status=status.HTTP_403_FORBIDDEN)
        ser = AppSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        app = GoogleCalendarApp.objects.filter(organization=membership.organization).first()
        if app is None and not d.get('client_secret'):
            return Response({'client_secret': ['Informe o segredo do cliente.']}, status=status.HTTP_400_BAD_REQUEST)
        app = app or GoogleCalendarApp(organization=membership.organization)
        app.client_id = d['client_id']
        if d.get('client_secret'):
            app.client_secret = d['client_secret']
        for field in ('enabled', 'share_details', 'event_minutes'):
            if field in d:
                setattr(app, field, d[field])
        app.save()
        audit.log('connection.updated', actor=request.user, organization=membership.organization, target=app,
                  changes={'provider': 'google_calendar', 'app': 'configured'})
        return Response({'ok': True})

    def delete(self, request):
        membership = _membership(request)
        if membership is None or membership.role not in MANAGE_TEAM_ROLES:
            return Response({'detail': 'Apenas donos ou administradores.'}, status=status.HTTP_403_FORBIDDEN)
        app = GoogleCalendarApp.objects.filter(organization=membership.organization).first()
        if app:
            for link in app.links.all():
                g.revoke(link.refresh_token)
            app.delete()
            audit.log('connection.deleted', actor=request.user, organization=membership.organization,
                      changes={'provider': 'google_calendar'})
        return Response(status=status.HTTP_204_NO_CONTENT)


def _pkce(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


class GCalConnectView(APIView):
    """POST — devolve a URL de autorização do Google (SPA: o front navega para ela). Usa o app OAuth do escritório."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        membership = _membership(request)
        app = GoogleCalendarApp.objects.filter(organization=membership.organization, enabled=True).first() if membership else None
        if app is None:
            return Response({'detail': 'O escritório ainda não configurou o app do Google.'}, status=status.HTTP_400_BAD_REQUEST)
        state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        params = {'client_id': app.client_id, 'redirect_uri': redirect_uri(request), 'response_type': 'code', 'scope': g.SCOPE,
                  'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true', 'state': state,
                  'code_challenge': _pkce(verifier), 'code_challenge_method': 'S256'}
        cookie = signing.dumps({'u': str(request.user.pk), 'a': app.pk, 's': state, 'v': verifier}, salt=SALT)
        response = Response({'authorization_url': f'{g.AUTH_URL}?{urlencode(params)}'})
        response.set_cookie(STATE_COOKIE, cookie, max_age=STATE_MAX_AGE, httponly=True, samesite='Lax', secure=not settings.DEBUG)
        return response


class GCalCallbackView(View):
    """GET público (o Google redireciona o navegador): confere state/cookie, troca o code com as credenciais do escritório e guarda o refresh token."""
    http_method_names = ['get']

    def _back(self, result):
        response = HttpResponseRedirect(f"{settings.FRONTEND_URL}/integracoes?gcal={result}")
        response.delete_cookie(STATE_COOKIE)
        response['Referrer-Policy'] = 'no-referrer'
        return response

    def get(self, request):
        if request.GET.get('error'):
            return self._back('denied')
        try:
            data = signing.loads(request.COOKIES.get(STATE_COOKIE, ''), salt=SALT, max_age=STATE_MAX_AGE)
        except signing.BadSignature:
            return self._back('state_invalid')
        if not secrets.compare_digest(str(data.get('s')), request.GET.get('state', '')) or not request.GET.get('code'):
            return self._back('state_invalid')
        app = GoogleCalendarApp.objects.filter(pk=data['a'], enabled=True).select_related('organization').first()
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.filter(pk=data['u'], is_active=True).first()
        if app is None or user is None or not app.organization.members.filter(user=user, is_active=True).exists():
            return self._back('state_invalid')
        try:
            tokens = g.exchange_code(app.client_id, app.client_secret, request.GET['code'], redirect_uri(request), data['v'])
        except g.GoogleAuthError:
            return self._back('code_rejected')
        refresh = tokens.get('refresh_token')
        if not refresh:
            return self._back('no_refresh_token')   # o Google só devolve na 1ª autorização: revogue o acesso e conecte de novo
        GoogleCalendarLink.objects.update_or_create(user=user, defaults={
            'app': app, 'refresh_token': refresh, 'status': GoogleCalendarLink.Status.ACTIVE, 'sync_token': '', 'last_error': ''})
        audit.log('connection.created', actor=user, organization=app.organization, changes={'provider': 'google_calendar'})
        return self._back('ok')


class GCalDisconnectView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        link = GoogleCalendarLink.objects.filter(user=request.user).first()
        if link:
            g.revoke(link.refresh_token)
            link.delete()   # TaskEventMap em cascata; as tarefas do Cadrius ficam; os eventos já criados ficam no Google
            audit.log('connection.deleted', actor=request.user, changes={'provider': 'google_calendar'})
        return Response(status=status.HTTP_204_NO_CONTENT)


class GCalSyncNowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        link = GoogleCalendarLink.objects.select_related('app', 'user').filter(user=request.user, status='active').first()
        if link is None:
            return Response({'detail': 'Google Calendar não conectado.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(pull_link(link))
        except g.GoogleRetryable:
            return Response({'detail': 'Google indisponível agora. Tente em instantes.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
