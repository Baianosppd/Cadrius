"""Google Calendar por escritório (CAD-162).

**Cada cliente (escritório) usa o PRÓPRIO app OAuth do Google** (``GoogleCalendarApp``): o Cadrius não precisa passar pela verificação do
Google para o escopo sensível de agenda — quem aprova/limita o app é o próprio escritório (app "Interno" no Workspace, ou "Em teste").
"""
from django.conf import settings
from django.db import models

from core.utils import EncryptedTextField


class GoogleCalendarApp(models.Model):
    organization = models.OneToOneField('accounts.Organization', on_delete=models.CASCADE, related_name='gcal_app')
    client_id = models.CharField(max_length=255)
    client_secret = EncryptedTextField()
    enabled = models.BooleanField(default=True)
    # False = o evento no Google leva só "Tarefa Cadrius" (sem título/descrição): evita dado sensível em calendário de terceiros
    share_details = models.BooleanField(default=True)
    event_minutes = models.PositiveSmallIntegerField(default=30, help_text='Duração padrão do evento.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Google Calendar de {self.organization_id}'


class GoogleCalendarLink(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativa'
        NEEDS_REAUTH = 'needs_reauth', 'Precisa reconectar'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='gcal_link')
    app = models.ForeignKey(GoogleCalendarApp, on_delete=models.CASCADE, related_name='links')
    refresh_token = EncryptedTextField()
    calendar_id = models.CharField(max_length=255, default='primary')
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.ACTIVE)
    sync_token = models.TextField(blank=True, default='')
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default='')
    connected_at = models.DateTimeField(auto_now_add=True)


class TaskEventMap(models.Model):
    """Liga uma tarefa do Cadrius ao evento correspondente no Google (para atualizar em vez de duplicar)."""

    task = models.OneToOneField('tasks.UserTask', on_delete=models.CASCADE, related_name='gcal_event')
    link = models.ForeignKey(GoogleCalendarLink, on_delete=models.CASCADE, related_name='events')
    event_id = models.CharField(max_length=255)
    last_synced_at = models.DateTimeField()
