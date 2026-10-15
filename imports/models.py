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


class FolderImport(models.Model):
    """CAD-234: carteira de clientes organizada em pastas (pasta = cliente, arquivos = documentos), vinda do Google Drive ou de
    um .zip (o "Fazer download" de uma pasta do Drive). A prévia (plano) fica cifrada; o .zip é apagado ao terminar."""

    class Source(models.TextChoices):
        DRIVE = 'drive', 'Google Drive'
        ZIP = 'zip', 'Arquivo .zip'

    class Status(models.TextChoices):
        LISTED = 'listed', 'Prévia pronta'
        RUNNING = 'running', 'Importando'
        DONE = 'done', 'Importado'
        FAILED = 'failed', 'Falhou'
        CANCELED = 'canceled', 'Cancelado'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='folder_imports')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    source = models.CharField(max_length=10, choices=Source.choices)
    label = models.CharField(max_length=255)                       # nome da pasta raiz ou do .zip
    drive_folder_id = models.CharField(max_length=128, blank=True, default='')
    archive_path = models.CharField(max_length=500, blank=True, default='')   # .zip em pasta privada; apagado ao terminar
    plan = EncryptedJSONField(default=list, blank=True)            # [{nome, documento, arquivos: [{nome, ref, tamanho, mime}]}]
    options = models.JSONField(default=dict, blank=True)           # {selecionadas: [i...], ler_com_ia: bool}
    progress = models.JSONField(default=dict, blank=True)          # {feitas, total, contatos_novos, contatos_existentes, documentos, erros}
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.LISTED)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
