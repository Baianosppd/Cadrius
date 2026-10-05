"""Caixa de publicações (CAD-173): comunicações processuais do DJEN capturadas pela OAB dos advogados do escritório,
triadas (ato, prazo provável, providência) e confirmadas por uma pessoa — só então viram prazo/tarefa.

O teor é público (Diário de Justiça), mas traz nomes de partes: fica cifrado em repouso como o resto do Cadrius."""
from django.conf import settings
from django.db import models

from core.pii import PIIIndexMixin
from core.utils import EncryptedJSONField, EncryptedTextField


class OabWatch(models.Model):
    """OAB acompanhada no DJEN (uma por advogado do escritório)."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='oab_watches')
    numero = models.CharField(max_length=10)                       # só dígitos
    uf = models.CharField(max_length=2)
    nome = models.CharField(max_length=120, blank=True, default='')  # nome do advogado (como aparece no Diário)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    is_active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uf', 'numero']
        constraints = [models.UniqueConstraint(fields=['organization', 'numero', 'uf'], name='uniq_oab_watch_per_org')]

    def __str__(self):
        return f'OAB {self.numero}/{self.uf}'


class Publication(PIIIndexMixin, models.Model):
    BLIND_INDEXES = {'cnj': ('cnj_bidx', 'case.cnj', 'digits')}       # mesma finalidade do processo acompanhado: casa os dois

    class Status(models.TextChoices):
        NEW = 'nova', 'Nova'
        CONFIRMED = 'confirmada', 'Confirmada'
        DISCARDED = 'descartada', 'Descartada'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='publications')
    watch = models.ForeignKey(OabWatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='publications')
    source = models.CharField(max_length=10, default='djen')
    external_id = models.CharField(max_length=64)
    tribunal = models.CharField(max_length=20, blank=True, default='')
    tipo = models.CharField(max_length=80, blank=True, default='')        # tipo de comunicação (Intimação, Edital…)
    orgao = models.CharField(max_length=255, blank=True, default='')
    classe = models.CharField(max_length=255, blank=True, default='')
    cnj = EncryptedTextField(blank=True, default='')
    cnj_bidx = models.CharField(max_length=64, null=True, blank=True, editable=False, db_index=True)
    texto = EncryptedTextField(blank=True, default='')
    partes = EncryptedJSONField(default=list, blank=True)
    link = models.URLField(max_length=500, blank=True, default='')
    disponibilizada_em = models.DateField(db_index=True)
    publicada_em = models.DateField(null=True, blank=True)               # 1º dia útil após a disponibilização (Lei 11.419)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    triage = EncryptedJSONField(default=dict, blank=True)                 # sugestão: ato, prazo_dias, fatal, providencia, resumo…
    vencimento = models.DateField(null=True, blank=True)
    case = models.ForeignKey('research.MonitoredCase', null=True, blank=True, on_delete=models.SET_NULL, related_name='publications')
    task = models.ForeignKey('tasks.UserTask', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-disponibilizada_em', '-pk']
        constraints = [models.UniqueConstraint(fields=['organization', 'external_id'], name='uniq_publication_per_org')]
        indexes = [models.Index(fields=['organization', 'status', '-disponibilizada_em'])]
