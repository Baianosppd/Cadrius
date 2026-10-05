"""Monitoramento de processos e notícias (CAD-166). Número do processo cifrado (com índice cego); andamentos são dados públicos do tribunal."""
from django.conf import settings
from django.db import models

from core.pii import PIIIndexMixin
from core.utils import EncryptedTextField


class MonitoredCase(PIIIndexMixin, models.Model):
    BLIND_INDEXES = {'cnj': ('cnj_bidx', 'case.cnj', 'digits')}

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='monitored_cases')
    cnj = EncryptedTextField()                                   # número formatado, cifrado em repouso
    cnj_bidx = models.CharField(max_length=64, editable=False, db_index=True)
    tribunal = models.CharField(max_length=12)                   # alias do DataJud (tjsp, trf1...)
    label = EncryptedTextField(blank=True, default='')            # apelido interno (pode conter nome de cliente)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    client = models.ForeignKey('contacts.Contact', null=True, blank=True, on_delete=models.SET_NULL, related_name='cases')  # CAD-172
    is_active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_movement_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['organization', 'cnj_bidx'], name='uniq_case_per_org')]


class CaseMovement(models.Model):
    case = models.ForeignKey(MonitoredCase, on_delete=models.CASCADE, related_name='movements')
    occurred_at = models.DateTimeField(null=True, blank=True)
    code = models.CharField(max_length=20, blank=True, default='')
    name = models.CharField(max_length=255)
    complement = models.CharField(max_length=500, blank=True, default='')
    digest = models.CharField(max_length=40)                     # identifica o andamento (evita duplicar a cada consulta)
    notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-occurred_at', '-id']
        constraints = [models.UniqueConstraint(fields=['case', 'digest'], name='uniq_movement_per_case')]


class NewsItem(models.Model):
    """Notícia de fonte pública configurada (RSS). Conteúdo público, compartilhado entre escritórios — sem dado pessoal."""
    source = models.CharField(max_length=80)
    url = models.URLField(max_length=500, unique=True)
    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True, default='')
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-published_at', '-id']
