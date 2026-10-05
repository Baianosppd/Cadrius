"""Regras de automação internas do escritório (CAD-172): "quando X acontecer, se Y, faça Z".

Diferente de ``workflows`` (fluxos disparados por webhooks de apps externos), aqui os gatilhos são eventos do próprio Cadrius
(documento confirmado, andamento novo, prazo chegando, contato novo, agenda). Regra nasce desligada; só liga depois de simulada
(com a configuração exata que vai rodar). Envio para fora do escritório (WhatsApp, e-mail, ERP) passa por aprovação humana por
padrão e só vai a contatos com consentimento no canal."""
import hashlib
import json

from django.conf import settings
from django.db import models

from core.utils import EncryptedJSONField, EncryptedTextField


class Rule(models.Model):
    class Trigger(models.TextChoices):
        DOCUMENT_CONFIRMED = 'document_confirmed', 'Documento confirmado'
        CASE_MOVEMENT = 'case_movement', 'Andamento novo no processo'
        DEADLINE_SOON = 'deadline_soon', 'Prazo chegando'
        CONTACT_CREATED = 'contact_created', 'Contato cadastrado'
        SCHEDULE = 'schedule', 'Agenda (diária/semanal)'
        PUBLICATION_NEW = 'publication_new', 'Publicação nova (DJEN)'
        RECEIVABLE_DUE = 'receivable_due', 'Honorário vencendo ou vencido'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='automation_rules')
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default='')
    enabled = models.BooleanField(default=False)
    trigger = models.CharField(max_length=30, choices=Trigger.choices)
    trigger_config = models.JSONField(default=dict, blank=True)
    conditions = models.JSONField(default=list, blank=True)       # [{field, op, value}] — todas precisam valer (E)
    actions = models.JSONField(default=list, blank=True)          # [{type, params}] — executadas em ordem
    require_approval = models.BooleanField(default=True)          # envios para fora esperam aprovação humana
    template_key = models.CharField(max_length=60, blank=True, default='')
    simulated_hash = models.CharField(max_length=64, blank=True, default='')   # configuração que passou pela simulação
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    run_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization', 'trigger', 'enabled'])]

    def config_hash(self) -> str:
        raw = json.dumps([self.trigger, self.trigger_config, self.conditions, self.actions, self.require_approval],
                         sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def simulated(self) -> bool:
        return bool(self.simulated_hash) and self.simulated_hash == self.config_hash()


class RuleRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = 'running', 'Executando'
        SUCCESS = 'success', 'Concluída'
        PARTIAL = 'partial', 'Concluída com falhas'
        FAILED = 'failed', 'Falhou'
        SKIPPED = 'skipped', 'Condições não atendidas'
        PENDING = 'pending_approval', 'Aguardando aprovação'
        REJECTED = 'rejected', 'Recusada'
        EXPIRED = 'expired', 'Aprovação expirada'

    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name='runs')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    trigger = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING, db_index=True)
    title = EncryptedTextField(blank=True, default='')            # "Processo 0001234-…" (pode ter nome de cliente)
    steps = EncryptedJSONField(default=list, blank=True)          # passos renderizados (mensagens com dados pessoais)
    dedupe_key = models.CharField(max_length=120)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['rule', 'dedupe_key'], name='uniq_rule_run_dedupe')]
