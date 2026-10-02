"""Eventos de autenticação e de administração capturados por signals."""
from __future__ import annotations

from axes.signals import user_locked_out
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from audit import service
from audit.redaction import mask_email

_ADMIN_ACTIONS = {ADDITION: 'admin.add', CHANGE: 'admin.change', DELETION: 'admin.delete'}


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    action = 'admin.login' if user.is_staff and request is not None and request.path.startswith('/admin') \
        else 'auth.login.success'
    service.log(action, actor=user, data_categories=['identificacao'], legal_basis='contrato')


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        service.log('auth.logout', actor=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get('username') or (credentials or {}).get('email') or ''
    service.log(
        'auth.login.failure', outcome='denied', actor_type='anonymous',
        actor_label=mask_email(username) or '(desconhecido)',
        reason='credenciais inválidas',
    )


@receiver(user_locked_out)
def on_locked_out(sender, request=None, username=None, ip_address=None, **kwargs):
    service.log(
        'auth.login.locked', outcome='denied', actor_type='anonymous',
        actor_label=mask_email(username or '') or '(desconhecido)',
        reason='bloqueio por excesso de tentativas (django-axes)',
    )


@receiver(post_save, sender=LogEntry)
def on_admin_log_entry(sender, instance: LogEntry, created, **kwargs):
    """Todo add/change/delete no Django Admin vira evento imutável (RNE-012 / RNF-009)."""
    if not created:
        return
    action = _ADMIN_ACTIONS.get(instance.action_flag)
    if action is None:
        return
    model = instance.content_type.model_class() if instance.content_type_id else None
    service.log(
        action,
        actor=instance.user,
        target_type=model._meta.label if model else 'desconhecido',
        target_id=str(instance.object_id or ''),
        # change_message traz só nomes de campos alterados (não os valores).
        changes={'fields': instance.get_change_message()[:200]},
        data_categories=['administrativo'],
    )
