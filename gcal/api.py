"""API do Google Calendar por escritório (CAD-162). Prefixo: /api/v1/integrations/google-calendar/"""
from __future__ import annotations

import base64
import logging
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.views import View
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from gcal import google_api as g
from gcal.models import ExternalEvent, GoogleCalendarApp, GoogleCalendarLink
from gcal.sync import pull_link

logger = logging.getLogger(__name__)

STATE_MAX_AGE = 600
SALT = 'cadrius.gcal'
# CAD-225: o "state" do OAuth fica no servidor (cache, uso único), e não num cookie. O cookie era gravado numa
# chamada da tela (app-teste → api-teste) sem credenciais e o navegador o descartava: todo retorno virava "state_invalid".
PENDING_KEY = 'gcal:oauth:{}'


def _pending_key(nonce: str) -> str:
    return PENDING_KEY.format(hashlib.sha256(nonce.encode()).hexdigest())


def redirect_uri(request=None) -> str:
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/')
    if not base and request is not None:
        base = request.build_absolute_uri('/').rstrip('/')
    return f'{base}/api/v1/integrations/google-calendar/callback/'


class AppSerializer(serializers.Serializer):
    client_id = serializers.CharField(max_length=255, required=False)
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
        from gcal import platform
        own_app = bool(app and app.enabled and not app.uses_platform)
        return Response({
            # CAD-230: com o app da plataforma, a pessoa conecta sem o escritório configurar nada no Google Cloud
            'app_configured': own_app or platform.platform_available(),
            'own_app': own_app,
            'platform_available': platform.platform_available(),
            'google_email': link.google_email if link else '',
            'recursos': {'agenda': bool(link), 'planilhas_documentos': bool(link and link.has_scope(platform.DRIVE_FILE))},
            'client_id': app.client_id if own_app else '',
            'share_details': app.share_details if app else True,
            'event_minutes': app.event_minutes if app else 30,
            'can_configure': membership.role in MANAGE_TEAM_ROLES,
            'connected': bool(link),
            'status': link.status if link else None,
            'last_sync_at': link.last_sync_at if link else None,
            'last_error': link.last_error if link else '',
            'redirect_uri': redirect_uri(request),
            'scope': platform.scopes(),
            # CAD-222: compromissos criados direto no Google
            'import_events': link.import_events if link else True,
            'lookahead_days': link.lookahead_days if link else 60,
            'task_kinds': link.task_kinds if link else ['prazo', 'audiencia'],
            'events_synced_at': link.events_synced_at if link else None,
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
        if d.get('client_id'):
            # app próprio do escritório: troca o da plataforma (quem já conectou precisa reconectar com o app novo)
            switching = app is None or app.uses_platform or app.client_id != d['client_id']
            if switching and not d.get('client_secret'):
                return Response({'client_secret': ['Informe o segredo do cliente.']}, status=status.HTTP_400_BAD_REQUEST)
            if app is not None and switching:
                app.links.update(status=GoogleCalendarLink.Status.NEEDS_REAUTH, last_error='O escritório trocou o app do Google.')
            app = app or GoogleCalendarApp(organization=membership.organization)
            app.client_id, app.uses_platform = d['client_id'], False
            if d.get('client_secret'):
                app.client_secret = d['client_secret']
        elif app is None:
            from gcal import platform
            app = platform.app_for(membership.organization)        # só preferências, com o app do Cadrius
            if app is None:
                return Response({'client_id': ['Informe o ID do cliente do Google.']}, status=status.HTTP_400_BAD_REQUEST)
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
        from gcal import platform
        app = platform.app_for(membership.organization) if membership else None
        if app is None:
            return Response({'detail': 'O Google ainda não está disponível para este escritório. Peça ao suporte do Cadrius '
                                       'ou cadastre o app do Google do escritório.'}, status=status.HTTP_400_BAD_REQUEST)
        nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        state = signing.dumps({'n': nonce}, salt=SALT)
        cache.set(_pending_key(nonce), {'u': str(request.user.pk), 'a': app.pk, 'v': verifier}, STATE_MAX_AGE)
        params = {'client_id': app.credentials()[0], 'redirect_uri': redirect_uri(request), 'response_type': 'code',
                  'scope': platform.scopes() if app.uses_platform else f'{g.SCOPE} {platform.DRIVE_FILE} {platform.IDENTITY}',
                  'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true', 'state': state,
                  'code_challenge': _pkce(verifier), 'code_challenge_method': 'S256'}
        return Response({'authorization_url': f'{g.AUTH_URL}?{urlencode(params)}'})


class GCalCallbackView(View):
    """GET público (o Google redireciona o navegador): confere o state (assinado + pendente no servidor, uso único), troca o code
    com as credenciais do escritório e guarda o refresh token."""
    http_method_names = ['get']

    def _back(self, result):
        response = HttpResponseRedirect(f"{settings.FRONTEND_URL}/integracoes?gcal={result}")
        response['Referrer-Policy'] = 'no-referrer'
        return response

    def get(self, request):
        if request.GET.get('error'):
            return self._back('denied')
        try:
            nonce = signing.loads(request.GET.get('state', ''), salt=SALT, max_age=STATE_MAX_AGE)['n']
        except (signing.BadSignature, KeyError, TypeError):
            return self._back('state_invalid')
        data = cache.get(_pending_key(nonce))
        cache.delete(_pending_key(nonce))                    # uso único
        if not data or not request.GET.get('code'):
            return self._back('state_invalid')
        app = GoogleCalendarApp.objects.filter(pk=data['a'], enabled=True).select_related('organization').first()
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.filter(pk=data['u'], is_active=True).first()
        if app is None or user is None or not app.organization.members.filter(user=user, is_active=True).exists():
            return self._back('state_invalid')
        try:
            cid, secret = app.credentials()
            tokens = g.exchange_code(cid, secret, request.GET['code'], redirect_uri(request), data['v'])
        except g.GoogleAuthError as exc:
            logger.warning('Google Agenda: troca do código recusada (%s)', str(exc)[:120])
            reason = {'redirect_uri_mismatch': 'redirect_mismatch', 'invalid_grant': 'code_expired'}.get(getattr(exc, 'code', ''), 'code_rejected')
            return self._back(reason)
        refresh = tokens.get('refresh_token')
        if not refresh:
            return self._back('no_refresh_token')   # o Google só devolve na 1ª autorização: revogue o acesso e conecte de novo
        GoogleCalendarLink.objects.update_or_create(user=user, defaults={
            'app': app, 'refresh_token': refresh, 'status': GoogleCalendarLink.Status.ACTIVE, 'sync_token': '', 'last_error': '',
            'scopes': str(tokens.get('scope') or '')[:2000], 'google_email': _email_from_id_token(tokens.get('id_token'))})
        audit.log('connection.created', actor=user, organization=app.organization, changes={'provider': 'google_calendar'})
        return self._back('ok')


def _email_from_id_token(id_token) -> str:
    """Só para mostrar "conectado como fulano@…": o token veio direto do Google (TLS, troca do code), sem uso de autorização."""
    if not id_token:
        return ''
    try:
        import jwt
        return str(jwt.decode(id_token, options={'verify_signature': False}).get('email') or '')[:254]
    except Exception:  # noqa: BLE001
        return ''


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
            from gcal.events import pull_external
            return Response({**pull_link(link), 'compromissos': pull_external(link, force=True)})
        except g.GoogleRetryable:
            return Response({'detail': 'Google indisponível agora. Tente em instantes.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# ----------------------------------------------------------------------------- compromissos do Google (CAD-222)


def event_json(e: ExternalEvent) -> dict:
    return {'id': e.pk, 'titulo': e.title, 'tipo': e.kind, 'tipo_label': e.get_kind_display(), 'inicio': e.start, 'fim': e.end,
            'dia_inteiro': e.all_day, 'local': e.location, 'processo': e.case.cnj if e.case_id else '', 'processo_id': e.case_id,
            'cliente': e.contact.name if e.contact_id else '', 'cliente_id': e.contact_id, 'tarefa_id': e.task_id,
            'tipo_corrigido': e.kind_locked}


class GCalSettingsView(APIView):
    """PATCH {import_events, lookahead_days, task_kinds} — o que trazer do Google e o que vira tarefa."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        link = GoogleCalendarLink.objects.filter(user=request.user).first()
        if link is None:
            return Response({'detail': 'Conecte o Google Agenda primeiro.'}, status=status.HTTP_400_BAD_REQUEST)
        data = request.data
        if 'import_events' in data:
            link.import_events = bool(data['import_events'])
        if 'lookahead_days' in data:
            try:
                link.lookahead_days = max(7, min(int(data['lookahead_days']), 180))
            except (TypeError, ValueError):
                return Response({'detail': 'Dias à frente: número entre 7 e 180.'}, status=status.HTTP_400_BAD_REQUEST)
        if 'task_kinds' in data:
            kinds = data['task_kinds'] if isinstance(data['task_kinds'], list) else []
            valid = {k for k, _ in ExternalEvent.Kind.choices}
            link.task_kinds = [k for k in kinds if k in valid]
        link.save(update_fields=['import_events', 'lookahead_days', 'task_kinds'])
        return Response({'import_events': link.import_events, 'lookahead_days': link.lookahead_days, 'task_kinds': link.task_kinds})


class GCalEventsView(APIView):
    """GET — próximos compromissos trazidos do Google (da própria pessoa; dono/admin veem os do escritório com ?todos=1)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        membership = _membership(request)
        if membership is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        qs = ExternalEvent.objects.filter(organization=membership.organization, cancelled=False,
                                          start__gte=timezone.now() - timedelta(days=1)).select_related('case', 'contact')
        if not (request.query_params.get('todos') and membership.role in MANAGE_TEAM_ROLES):
            qs = qs.filter(link__user=request.user)
        kind = request.query_params.get('tipo')
        if kind:
            qs = qs.filter(kind=kind)
        return Response([event_json(e) for e in qs[:200]])

    def post(self, request):
        """CAD-230: cria o compromisso direto no Google Agenda da pessoa.
        {titulo, inicio (ISO), duracao_min, local, descricao, convidados[], avisar_convidados, dia_inteiro}"""
        membership = _membership(request)
        if membership is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        from gcal import write
        d = request.data
        inicio = _parse_start(d.get('inicio'))
        if inicio is None:
            return Response({'detail': 'Informe data e hora de início.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ev = write.create_event(request.user, membership.organization, titulo=str(d.get('titulo') or ''), inicio=inicio,
                                    duracao_min=_int(d.get('duracao_min'), 60), local=str(d.get('local') or ''),
                                    descricao=str(d.get('descricao') or ''), convidados=d.get('convidados') or [],
                                    avisar_convidados=bool(d.get('avisar_convidados')), dia_inteiro=bool(d.get('dia_inteiro')))
        except write.CalendarWriteError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(event_json(ev), status=status.HTTP_201_CREATED)


def _parse_start(value):
    from django.utils.dateparse import parse_datetime
    dt = parse_datetime(str(value or ''))
    if dt is None:
        return None
    return dt if timezone.is_aware(dt) else timezone.make_aware(dt)


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class GCalEventDetailView(APIView):
    """PATCH {tipo, cliente_id, processo_id} — corrige a classificação/vínculos (a correção não é desfeita pela sincronização).
    PATCH {titulo, inicio, duracao_min, local, descricao} muda o compromisso no Google; DELETE cancela (CAD-230)."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        membership = _membership(request)
        ev = ExternalEvent.objects.filter(pk=pk, organization=membership.organization if membership else None).first()
        if ev is None or (ev.link.user_id != request.user.id and membership.role not in MANAGE_TEAM_ROLES):
            return Response(status=status.HTTP_404_NOT_FOUND)
        data, fields = request.data, []
        if 'tipo' in data:
            if data['tipo'] not in ExternalEvent.Kind.values:
                return Response({'detail': 'Tipo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            ev.kind, ev.kind_locked = data['tipo'], True
            fields += ['kind', 'kind_locked']
        if 'cliente_id' in data:
            from contacts.models import Contact
            ev.contact = Contact.objects.filter(organization=ev.organization, pk=data['cliente_id']).first() if data['cliente_id'] else None
            fields.append('contact')
        if 'processo_id' in data:
            from research.models import MonitoredCase
            ev.case = MonitoredCase.objects.filter(organization=ev.organization, pk=data['processo_id']).first() if data['processo_id'] else None
            fields.append('case')
        if fields:
            ev.save(update_fields=fields)
            from gcal.events import _ensure_task
            _ensure_task(ev.link, ev)
        # CAD-230: mudar o próprio compromisso no Google (título, horário, duração, local, descrição)
        changes = {k: data[k] for k in ('titulo', 'inicio', 'duracao_min', 'local', 'descricao') if k in data}
        if changes:
            from gcal import write
            if ev.link.user_id != request.user.id:
                return Response({'detail': 'Só quem é dono do compromisso pode alterá-lo no Google.'}, status=status.HTTP_403_FORBIDDEN)
            inicio = _parse_start(changes['inicio']) if 'inicio' in changes else None
            if 'inicio' in changes and inicio is None:
                return Response({'detail': 'Data e hora inválidas.'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                ev = write.update_event(request.user, membership.organization, ev.pk, titulo=changes.get('titulo'), inicio=inicio,
                                        duracao_min=_int(changes['duracao_min'], 60) if 'duracao_min' in changes else None,
                                        local=changes.get('local'), descricao=changes.get('descricao'))
            except write.CalendarWriteError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(event_json(ev))

    def delete(self, request, pk):
        membership = _membership(request)
        if membership is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        from gcal import write
        try:
            write.cancel_event(request.user, membership.organization, pk)
        except write.CalendarWriteError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)
