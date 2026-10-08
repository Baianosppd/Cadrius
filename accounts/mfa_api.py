"""Endpoints de MFA (CAD-169). Prefixo: /api/v1/auth/mfa/"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts import mfa
from accounts.models import MFADevice
from audit import service as audit


def _status(user):
    return {'enabled': mfa.enabled(user), 'required': mfa.required(user),
            'recovery_codes_left': mfa.recovery_left(user) if mfa.enabled(user) else 0}


class MFAStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({**_status(request.user), 'session_has_mfa': mfa.request_has_mfa(request)})


class MFASetupView(APIView):
    """Gera um segredo NOVO (não confirmado) e devolve QR/URI. Não muda nada no login até a confirmação."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if mfa.enabled(request.user):
            return Response({'detail': 'A verificação em duas etapas já está ativa. Desative antes para trocar de aparelho.'},
                            status=status.HTTP_409_CONFLICT)
        secret = mfa.new_secret()
        MFADevice.objects.update_or_create(user=request.user, defaults={'secret': secret, 'confirmed_at': None, 'last_step': 0})
        uri = mfa.otpauth_uri(secret, request.user.email)
        return Response({'secret': secret, 'otpauth_uri': uri, 'qr_svg': mfa.qr_svg(uri)})


class MFAConfirmView(APIView):
    """Confirma com o 1º código do app: ativa, gera os códigos de recuperação e devolve tokens já com MFA."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_mfa'

    def post(self, request):
        user = request.user
        with transaction.atomic():
            device = MFADevice.objects.select_for_update().filter(user=user, confirmed_at__isnull=True).first()
            if device is None:
                return Response({'detail': 'Comece pelo cadastro do aplicativo (QR code).'}, status=status.HTTP_400_BAD_REQUEST)
            step = mfa.matching_step(device.secret, request.data.get('code'))
            if step is None:
                return Response({'detail': 'Código inválido. Confira o horário do celular e tente o código atual.'},
                                status=status.HTTP_400_BAD_REQUEST)
            device.confirmed_at, device.last_step = timezone.now(), step
            device.save(update_fields=['confirmed_at', 'last_step'])
        codes = mfa.new_recovery_codes(user)
        audit.log('auth.mfa.enabled', actor=user, data_categories=['credenciais'])
        return Response({'recovery_codes': codes, **mfa.issue_tokens(user, mfa=True), **_status(user)})


class MFADisableView(APIView):
    """Desativar pede a senha E um código (do app ou de recuperação)."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_mfa'

    def post(self, request):
        user = request.user
        if not user.check_password(str(request.data.get('password', ''))):
            return Response({'detail': 'Senha incorreta.'}, status=status.HTTP_400_BAD_REQUEST)
        if not mfa.enabled(user) or not mfa.check_code(user, request.data.get('code')):
            return Response({'detail': 'Código inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        mfa.disable(user)
        audit.log('auth.mfa.disabled', actor=user, reason='desativado pelo próprio usuário', data_categories=['credenciais'])
        return Response(_status(user))


class MFARecoveryCodesView(APIView):
    """Gera códigos de recuperação novos (os antigos deixam de valer). Pede um código do app."""
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_mfa'

    def post(self, request):
        if mfa.check_code(request.user, request.data.get('code')) != 'totp':
            return Response({'detail': 'Código do aplicativo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        codes = mfa.new_recovery_codes(request.user)
        audit.log('auth.mfa.recovery_regenerated', actor=request.user, data_categories=['credenciais'])
        return Response({'recovery_codes': codes})


class MFAVerifyView(APIView):
    """2º passo do login: {mfa_token, code} → tokens. 5 erros invalidam o desafio (volta para a senha)."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_mfa'

    def post(self, request):
        challenge = mfa.read_challenge(str(request.data.get('mfa_token', '')))
        if challenge is None:
            return Response({'detail': 'A verificação expirou. Entre novamente com sua senha.', 'code': 'mfa_expired'},
                            status=status.HTTP_401_UNAUTHORIZED)
        user = get_user_model().objects.filter(pk=challenge['u'], is_active=True).first()
        kind = mfa.check_code(user, request.data.get('code')) if user else None
        if kind is None:
            attempts = mfa.register_failure(challenge)
            audit.log('auth.mfa.failed', actor=user, actor_type='user' if user else 'anonymous', outcome='denied',
                      reason=f'código inválido ({attempts}/{mfa.MAX_ATTEMPTS})')
            if attempts >= mfa.MAX_ATTEMPTS:
                return Response({'detail': 'Muitas tentativas. Entre novamente com sua senha.', 'code': 'mfa_expired'},
                                status=status.HTTP_401_UNAUTHORIZED)
            return Response({'detail': 'Código inválido.', 'code': 'mfa_invalid'}, status=status.HTTP_400_BAD_REQUEST)
        mfa.kill_challenge(challenge)              # desafio de uso único
        from accounts.team_roles import get_active_membership
        membership = get_active_membership(user)
        audit.log('auth.login.success', actor=user, organization=membership.organization if membership else None,
                  reason=f'MFA ({kind}) via {challenge.get("via", "pwd")}', data_categories=['identificacao'], legal_basis='contrato')
        data = mfa.issue_tokens(user, mfa=True, remember=challenge.get('r', True))
        if kind == 'recovery':
            data['recovery_codes_left'] = mfa.recovery_left(user)
        return Response(data)
