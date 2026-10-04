"""Recuperação de senha por e-mail (CAD-115).

* ``POST /api/v1/auth/password-reset/``          {email}                  → sempre 202 (não revela se a conta existe)
* ``POST /api/v1/auth/password-reset/confirm/``  {uid, token, new_password} → 200 | 400

Segurança: token de uso único (muda o hash da senha), validade ``PASSWORD_RESET_TIMEOUT`` (1 h), link com o token no
*fragmento* da URL (não vai ao servidor nem ao ``Referer``), throttle por IP e por e-mail, revogação de todas as
sessões ao concluir e trilha de auditoria. Falha de envio nunca vira erro para quem pediu (anti-enumeração).
"""
from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from audit import service as audit

logger = logging.getLogger(__name__)
User = get_user_model()

PER_EMAIL_LIMIT = 3          # e-mails de recuperação por endereço…
PER_EMAIL_WINDOW = 60 * 60   # …por hora (evita usar o Cadrius para encher a caixa de alguém)
GENERIC_MESSAGE = 'Se o e-mail estiver cadastrado, enviaremos as instruções para redefinir a senha.'
INVALID_LINK = 'Link inválido ou expirado. Solicite um novo.'


class RequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, style={'input_type': 'password'})


def _email_key(email: str) -> str:
    return 'pwreset:' + hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _allowed_for_email(email: str) -> bool:
    key = _email_key(email)
    cache.add(key, 0, PER_EMAIL_WINDOW)
    try:
        count = cache.incr(key)
    except ValueError:  # chave expirou entre add e incr
        cache.set(key, 1, PER_EMAIL_WINDOW)
        return True
    # Cache fora do ar (IGNORE_EXCEPTIONS) devolve None: recuperar a senha é crítico, então não bloqueia —
    # o throttle por IP e o monitoramento do Redis (readyz) cobrem o abuso.
    return count is None or count <= PER_EMAIL_LIMIT


def build_reset_url(user) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f'{settings.FRONTEND_URL}/redefinir-senha#uid={uid}&token={token}'


def send_reset_email(user) -> None:
    minutes = int(getattr(settings, 'PASSWORD_RESET_TIMEOUT', 3600) // 60)
    name = (user.first_name or '').strip() or 'olá'
    body = (
        f'Olá, {name}.\n\n'
        'Recebemos um pedido para redefinir a senha da sua conta no Cadrius. '
        f'Use o link abaixo (vale por {minutes} minutos e só pode ser usado uma vez):\n\n'
        f'{build_reset_url(user)}\n\n'
        'Se você não fez esse pedido, ignore este e-mail: sua senha continua a mesma.\n\n'
        '— Equipe Cadrius'
    )
    send_mail('Redefinição de senha — Cadrius', body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


class PasswordResetRequestView(APIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = ()
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'

    def post(self, request):
        serializer = RequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email'].strip()

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None and user.has_usable_password() and _allowed_for_email(email):
            try:
                send_reset_email(user)
                audit.log('auth.password.reset_requested', actor=user, data_categories=['contato'], legal_basis='contrato')
            except Exception:  # noqa: BLE001 — falha de SMTP não pode revelar nem derrubar o pedido
                logger.exception('Falha ao enviar e-mail de recuperação de senha')
                audit.log('auth.password.reset_requested', actor=user, outcome='error', reason='falha no envio de e-mail')
        elif user is None:
            audit.log('auth.password.reset_requested', actor_type='anonymous', outcome='denied',
                      reason='e-mail não cadastrado', changes={'email_hash': _email_key(email)[-12:]})
        return Response({'detail': GENERIC_MESSAGE}, status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    permission_classes = (permissions.AllowAny,)
    authentication_classes = ()
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'

    def post(self, request):
        serializer = ConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(data['uid'])), is_active=True)
        except (User.DoesNotExist, DjangoValidationError, ValueError, TypeError, OverflowError, UnicodeDecodeError):
            user = None
        if user is None or not default_token_generator.check_token(user, data['token']):
            audit.log('auth.password.reset', actor_type='anonymous', outcome='denied', reason='token inválido ou expirado')
            return Response({'detail': INVALID_LINK, 'code': 'invalid_token'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(data['new_password'], user)
        except DjangoValidationError as exc:
            return Response({'new_password': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(data['new_password'])
        user.save(update_fields=['password'])
        # Encerra todas as sessões: quem tinha a senha antiga (ou um refresh roubado) perde o acesso.
        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)
        audit.log('auth.password.reset', actor=user, reason='senha redefinida por e-mail; sessões encerradas')
        return Response({'detail': 'Senha redefinida. Entre com a nova senha.'}, status=status.HTTP_200_OK)
