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
        # CAD-222: mais pontos de partida para tirar trabalho manual do dia a dia
        EMAIL_RECEIVED = 'email_received', 'E-mail recebido (triado)'
        CALENDAR_EVENT = 'calendar_event', 'Compromisso da Agenda Google chegando'
        TASK_OVERDUE = 'task_overdue', 'Tarefa atrasada'
        RECEIVABLE_PAID = 'receivable_paid', 'Pagamento recebido'
        OPPORTUNITY_STAGE = 'opportunity_stage', 'Oportunidade mudou de etapa'
        AGREEMENT_CREATED = 'agreement_created', 'Contrato de honorários criado'
        DOCUMENT_UPLOADED = 'document_uploaded', 'Documento enviado'
        PORTAL_VIEWED = 'portal_viewed', 'Cliente abriu o portal'
        # CAD-223
        LEAD_CAPTURED = 'lead_captured', 'Contato pelo formulário de captação'
        SURVEY_ANSWERED = 'survey_answered', 'Cliente respondeu a pesquisa de satisfação'
        NFSE_ISSUED = 'nfse_issued', 'Nota fiscal de honorários emitida'
        EXPENSE_CREATED = 'expense_created', 'Despesa lançada'
        COURT_SUSPENSION = 'court_suspension', 'Suspensão de prazos no tribunal'
        CONTACT_BIRTHDAY = 'contact_birthday', 'Aniversário do cliente'
        OPPORTUNITY_STALE = 'opportunity_stale', 'Oportunidade parada no funil'
        CASE_STALE = 'case_stale', 'Processo sem andamento'
        CONTRACT_ENDING = 'contract_ending', 'Contrato de honorários terminando'
        MONTHLY_GOAL = 'monthly_goal', 'Acompanhamento da meta do mês'
        # CAD-226: relógio, celular ou assistente de voz chamam uma URL secreta da regra
        SHORTCUT = 'shortcut', 'Atalho (relógio, celular ou voz)'

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
    shortcut_key_hash = models.CharField(max_length=64, blank=True, default='')   # CAD-226: SHA-256 da chave do atalho (a chave só aparece 1 vez)
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
        SCHEDULED = 'scheduled', 'Agendada (fora do horário comercial)'

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


class PersonalDevice(models.Model):
    """CAD-227: relógio, celular ou assistente de voz de UMA pessoa. A chave (mostrada uma vez) autentica os comandos de voz
    e, se ``can_approve``, as aprovações pelo relógio. O banco guarda só o SHA-256 da chave."""

    class Kind(models.TextChoices):
        APPLE = 'apple', 'Apple Watch / iPhone (Siri)'
        WEAR = 'wear', 'Android / Wear OS'
        ALEXA = 'alexa', 'Alexa'
        GOOGLE = 'google', 'Google Assistente'
        OTHER = 'outro', 'Outro (botão, NFC, automação)'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='personal_devices')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='personal_devices')
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.APPLE)
    key_hash = models.CharField(max_length=64, unique=True)
    can_approve = models.BooleanField(default=False)
    notify = models.BooleanField(default=False)                     # avisos de aprovação pendente (ntfy)
    ntfy_topic = models.CharField(max_length=60, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def active(self) -> bool:
        return self.revoked_at is None
