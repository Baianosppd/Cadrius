"""Sessão que não cansa o cliente (CAD-232).

Antes o refresh token valia 1 dia fixo e o "Manter conectado" do login não fazia nada: o advogado precisava entrar de
novo todo dia. Agora:

- **Manter conectado (padrão):** a sessão vale ``SESSION_REMEMBER_DAYS`` (30) dias e se renova a cada uso (rotação do
  refresh token). Quem usa o Cadrius pelo menos uma vez por mês nunca mais vê a tela de login.
- **Sem marcar:** 1 dia (``REFRESH_TOKEN_LIFETIME``), também renovado no uso. Para computador compartilhado.
- **Equipe Cadrius (Gestão):** nunca fica "lembrada": no máximo 1 dia, com MFA.
- **Segurança:** cada renovação invalida o token anterior (blacklist). Sair, trocar a senha ou a TI encerrar as sessões
  continua derrubando tudo.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

CLAIM = 'lembrar'


def remember_lifetime() -> timedelta:
    return timedelta(days=int(getattr(settings, 'SESSION_REMEMBER_DAYS', 30)))


class SessionRefreshToken(RefreshToken):
    """Refresh token que guarda se a pessoa pediu para ficar conectada e mantém esse prazo ao ser renovado."""

    def set_exp(self, claim='exp', from_time=None, lifetime=None):
        if lifetime is None and claim == 'exp' and self.payload.get(CLAIM):
            lifetime = remember_lifetime()
        super().set_exp(claim, from_time, lifetime)


def issue(user, *, remember: bool = True) -> SessionRefreshToken:
    token = SessionRefreshToken.for_user(user)
    if remember and not getattr(user, 'is_staff', False):
        token[CLAIM] = True
        token.set_exp()
        OutstandingToken.objects.filter(jti=token['jti']).update(expires_at=token.current_time + remember_lifetime())
    return token


class SessionRefreshSerializer(TokenRefreshSerializer):
    token_class = SessionRefreshToken


def wants_remember(value) -> bool:
    """O front manda ``lembrar``; sem o campo (apps antigos), mantém conectado."""
    if value is None or value == '':
        return True
    return str(value).lower() in ('1', 'true', 'sim', 'on')
