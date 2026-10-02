from django.db import models
from django.utils import timezone


class ControlAssessment(models.Model):
    """
    Avaliação MANUAL de um controle (responsável, evidência, status). Controles com verificação
    automática mostram o resultado automático; esta avaliação complementa (ex.: política assinada,
    treinamento realizado, contrato com fornecedor).
    """

    class Status(models.TextChoices):
        IMPLEMENTED = 'implemented', 'Implementado'
        PARTIAL = 'partial', 'Parcial'
        NOT_IMPLEMENTED = 'not_implemented', 'Não implementado'
        NOT_APPLICABLE = 'not_applicable', 'Não aplicável'
        NOT_ASSESSED = 'not_assessed', 'Não avaliado'

    framework = models.CharField(max_length=16, db_index=True)   # iso27001 | iso27701 | lgpd
    control_id = models.CharField(max_length=16)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOT_ASSESSED)
    owner = models.CharField(max_length=120, blank=True, help_text='Responsável pelo controle.')
    evidence_url = models.CharField(max_length=500, blank=True, help_text='Link/documento que comprova.')
    justification = models.TextField(blank=True, help_text='Obrigatória para "Não aplicável".')
    reviewed_by = models.CharField(max_length=64, blank=True)
    reviewed_at = models.DateTimeField(default=timezone.now)
    next_review_at = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ('framework', 'control_id')
        ordering = ['framework', 'control_id']

    def __str__(self):
        return f'{self.framework} {self.control_id}: {self.status}'


class ComplianceSnapshot(models.Model):
    """Fotografia periódica da conformidade (evidência histórica para auditoria e tendência)."""

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    framework = models.CharField(max_length=16, db_index=True)
    score = models.FloatField()
    counts = models.JSONField(default=dict)
    failing = models.JSONField(default=list)

    class Meta:
        ordering = ['-created_at']
