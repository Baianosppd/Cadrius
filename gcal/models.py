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


def default_task_kinds():
    return ['prazo', 'audiencia']


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
    # CAD-222: trazer também os compromissos criados direto no Google (prazos, audiências, reuniões)
    import_events = models.BooleanField(default=True)
    lookahead_days = models.PositiveSmallIntegerField(default=60)
    task_kinds = models.JSONField(default=default_task_kinds, blank=True, help_text='Tipos que viram tarefa no Cadrius (prazo, audiencia…).')
    events_synced_at = models.DateTimeField(null=True, blank=True)


class TaskEventMap(models.Model):
    """Liga uma tarefa do Cadrius ao evento correspondente no Google (para atualizar em vez de duplicar)."""

    task = models.OneToOneField('tasks.UserTask', on_delete=models.CASCADE, related_name='gcal_event')
    link = models.ForeignKey(GoogleCalendarLink, on_delete=models.CASCADE, related_name='events')
    event_id = models.CharField(max_length=255)
    last_synced_at = models.DateTimeField()


class ExternalEvent(models.Model):
    """Compromisso criado direto no Google Agenda e trazido para o Cadrius (CAD-222). Classificado (prazo, audiência,
    reunião…), ligado ao processo/cliente quando o texto permite, e fonte do gatilho "Compromisso da Agenda chegando"."""

    class Kind(models.TextChoices):
        PRAZO = 'prazo', 'Prazo'
        AUDIENCIA = 'audiencia', 'Audiência'
        REUNIAO = 'reuniao', 'Reunião / atendimento'
        PERICIA = 'pericia', 'Perícia / diligência'
        OUTRO = 'outro', 'Outro compromisso'

    link = models.ForeignKey(GoogleCalendarLink, on_delete=models.CASCADE, related_name='external_events')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='external_events')
    event_id = models.CharField(max_length=255)
    title = EncryptedTextField(blank=True, default='')
    description = EncryptedTextField(blank=True, default='')
    location = EncryptedTextField(blank=True, default='')
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField(null=True, blank=True)
    all_day = models.BooleanField(default=False)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OUTRO, db_index=True)
    kind_locked = models.BooleanField(default=False)                 # a pessoa corrigiu o tipo: a sincronização não muda mais
    case = models.ForeignKey('research.MonitoredCase', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    contact = models.ForeignKey('contacts.Contact', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    task = models.ForeignKey('tasks.UserTask', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cancelled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start']
        constraints = [models.UniqueConstraint(fields=['link', 'event_id'], name='uniq_external_event_per_link')]
