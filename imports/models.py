"""Importação de planilhas (CAD-171). O conteúdo lido fica CIFRADO e só até a importação terminar (ou 7 dias): depois, só o resumo."""
from django.conf import settings
from django.db import models

from core.utils import EncryptedJSONField


class ImportJob(models.Model):
    class Target(models.TextChoices):
        CONTACTS = 'contacts', 'Contatos'
        CASES = 'cases', 'Processos (monitoramento)'

    class Status(models.TextChoices):
        UPLOADED = 'uploaded', 'Aguardando mapeamento'
        PREVIEWED = 'previewed', 'Simulado'
        DONE = 'done', 'Importado'
        CANCELED = 'canceled', 'Cancelado'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='import_jobs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    target = models.CharField(max_length=20, choices=Target.choices)
    filename = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    columns = models.JSONField(default=list)
    rows = EncryptedJSONField(default=list, blank=True)          # apagado ao concluir/cancelar ou após 7 dias
    rows_total = models.PositiveIntegerField(default=0)
    mapping = models.JSONField(default=dict, blank=True)          # índice da coluna (str) → campo do destino
    summary = models.JSONField(default=dict, blank=True)          # {'created', 'updated', 'skipped', 'errors'}
    errors = models.JSONField(default=list, blank=True)           # [{'row': n, 'errors': [...]}] — sem os valores da linha
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
