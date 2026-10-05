"""Contas da equipe Cadrius criadas pela TI (CAD-170). Sem senha definida aqui: a pessoa recebe o link de "definir senha" e cadastra o
MFA no 1º acesso à Gestão. Superusuário não nasce por esta tela (só pelo servidor)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts import mfa
from audit import service as audit
from backoffice.permissions import AREA_GROUPS, user_areas
from backoffice.services import ActionError, revoke_sessions


def staff_row(user) -> dict:
    return {'id': str(user.pk), 'email': user.email, 'nome': user.get_full_name(), 'areas': user_areas(user) if user.is_active else [],
            'superusuario': user.is_superuser, 'ativo': user.is_active, 'mfa': mfa.enabled(user),
            'ultimo_acesso': user.last_login, 'criado_em': user.date_joined}


def _clean_areas(areas) -> list[str]:
    if not isinstance(areas, (list, tuple)):
        raise ActionError('Áreas inválidas.')
    wanted = sorted({str(a) for a in areas})
    unknown = [a for a in wanted if a not in AREA_GROUPS]
    if unknown:
        raise ActionError(f'Área desconhecida: {", ".join(unknown)}.')
    return wanted


def _apply_areas(user, areas):
    for area, name in AREA_GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        (user.groups.add if area in areas else user.groups.remove)(group)


def create_staff(actor, *, email, first_name, last_name, areas, reason) -> dict:
    User = get_user_model()
    email = (email or '').strip().lower()
    try:
        validate_email(email)
    except ValidationError as exc:
        raise ActionError('E-mail inválido.') from exc
    areas = _clean_areas(areas)
    if not areas:
        raise ActionError('Escolha ao menos uma área.')
    if User.objects.filter(email__iexact=email).exists():
        raise ActionError('Já existe uma conta com este e-mail. Para dar acesso à Gestão, altere as áreas dela na lista da equipe.')
    with transaction.atomic():
        user = User(username=email, email=email, first_name=(first_name or '')[:150], last_name=(last_name or '')[:150], is_staff=True)
        user.set_unusable_password()                    # a senha é definida pela própria pessoa, pelo link enviado
        user.save()
        _apply_areas(user, areas)
    audit.log('backoffice.action', actor=actor, target=user, reason=reason[:255],
              changes={'action': 'staff_created', 'areas': areas})
    from accounts.password_reset import send_reset_email
    send_reset_email(user)
    return staff_row(user)


def update_staff(actor, user, *, areas, reason) -> dict:
    if user.is_superuser and not actor.is_superuser:
        raise ActionError('Só um superusuário altera outro superusuário.')
    areas = _clean_areas(areas)
    if user.pk == actor.pk and 'ti' not in areas:
        raise ActionError('Você não pode tirar a própria área de TI (evita ficar sem ninguém para administrar).')
    with transaction.atomic():
        _apply_areas(user, areas)
        revoked = 0
        if not areas and not user.is_superuser:
            user.is_staff = False                         # sem área = deixa de ser equipe; sessões encerradas
            user.save(update_fields=['is_staff'])
            revoked = revoke_sessions(user)
        elif areas and not user.is_staff:
            user.is_staff = True
            user.save(update_fields=['is_staff'])
    audit.log('backoffice.action', actor=actor, target=user, reason=reason[:255],
              changes={'action': 'staff_areas_changed', 'areas': areas})
    return {**staff_row(user), 'sessoes_encerradas': revoked}
