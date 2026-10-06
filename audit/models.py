import hashlib
import json
import uuid

from django.db import models
from django.utils import timezone

GENESIS_HASH = '0' * 64


class ImmutableError(RuntimeError):
    """Tentativa de alterar/apagar um registo de auditoria."""


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ImmutableError('AuditEvent é append-only: update() não é permitido.')

    def delete(self):
        raise ImmutableError('AuditEvent é append-only: delete() não é permitido.')

    def bulk_update(self, *args, **kwargs):
        raise ImmutableError('AuditEvent é append-only.')


class AuditEvent(models.Model):
    """
    Evento de auditoria IMUTÁVEL e encadeado por hash (cada evento inclui o hash do anterior).

    Camadas de proteção: (1) API do modelo recusa update/delete; (2) trigger no PostgreSQL
    (migration 0002) recusa UPDATE/DELETE/TRUNCATE; (3) a cadeia de hash detecta adulteração
    feita fora da aplicação (``verify_audit_chain``).
    """

    class Outcome(models.TextChoices):
        SUCCESS = 'success', 'Sucesso'
        DENIED = 'denied', 'Negado'
        ERROR = 'error', 'Erro'

    class ActorType(models.TextChoices):
        USER = 'user', 'Utilizador'
        ADMIN = 'admin', 'Administrador (staff)'
        SYSTEM = 'system', 'Sistema/worker'
        WEBHOOK = 'webhook', 'Webhook externo'
        ANONYMOUS = 'anonymous', 'Anónimo'

    seq = models.BigAutoField(primary_key=True)
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    request_id = models.CharField(max_length=64, blank=True, db_index=True)

    actor_type = models.CharField(max_length=16, choices=ActorType.choices, default=ActorType.ANONYMOUS)
    actor_id = models.CharField(max_length=64, blank=True, db_index=True)
    actor_label = models.CharField(max_length=255, blank=True, help_text='E-mail mascarado (j***@dominio).')
    # UUID simples (não FK): apagar uma Organization nunca pode apagar a sua trilha.
    organization_id = models.UUIDField(null=True, blank=True, db_index=True)

    action = models.CharField(max_length=64, db_index=True, help_text='categoria.verbo, ex.: auth.login.success')
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.SUCCESS)
    reason = models.CharField(max_length=255, blank=True)

    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent_hash = models.CharField(max_length=16, blank=True)
    auth_method = models.CharField(max_length=32, blank=True)

    changes = models.JSONField(default=dict, blank=True, help_text='Só nomes de campos/metadados — nunca valores pessoais.')
    data_categories = models.JSONField(default=list, blank=True)
    legal_basis = models.CharField(max_length=32, blank=True)

    prev_hash = models.CharField(max_length=64, editable=False)
    hash = models.CharField(max_length=64, editable=False, unique=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ['seq']
        verbose_name = 'Evento de auditoria'
        verbose_name_plural = 'Eventos de auditoria'
        indexes = [
            models.Index(fields=['organization_id', 'occurred_at']),
            models.Index(fields=['actor_id', 'occurred_at']),
            models.Index(fields=['action', 'occurred_at']),
        ]

    HASHED_FIELDS = (
        'uid', 'occurred_at', 'request_id', 'actor_type', 'actor_id', 'actor_label', 'organization_id',
        'action', 'target_type', 'target_id', 'outcome', 'reason', 'ip', 'user_agent_hash',
        'auth_method', 'changes', 'data_categories', 'legal_basis',
    )

    def canonical_payload(self) -> str:
        data = {}
        for name in self.HASHED_FIELDS:
            value = getattr(self, name)
            if hasattr(value, 'isoformat'):
                value = value.isoformat()
            data[name] = str(value) if name in ('uid', 'organization_id') and value is not None else value
        return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str)

    def compute_hash(self) -> str:
        return hashlib.sha256((self.prev_hash + self.canonical_payload()).encode()).hexdigest()

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise ImmutableError('AuditEvent é append-only: não pode ser alterado.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableError('AuditEvent é append-only: não pode ser apagado.')

    def __str__(self):
        return f'#{self.seq} {self.action} [{self.outcome}]'


class AuditChainHead(models.Model):
    """Linha única que guarda o último hash; serializa a escrita (select_for_update) e evita bifurcações."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    last_seq = models.BigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, default=GENESIS_HASH)


class AuditCheckpoint(models.Model):
    """Registo de expurgos por retenção: a verificação da cadeia recomeça no ``last_hash`` indicado."""

    created_at = models.DateTimeField(auto_now_add=True)
    purged_until_seq = models.BigIntegerField()
    last_hash = models.CharField(max_length=64)
    purged_count = models.PositiveIntegerField()
    reason = models.CharField(max_length=255, default='retention')


class AnomalyAlert(models.Model):
    """Alerta de comportamento fora do padrão (inclusive de utilizadores autenticados)."""

    class Severity(models.TextChoices):
        LOW = 'low', 'Baixa'
        MEDIUM = 'medium', 'Média'
        HIGH = 'high', 'Alta'
        CRITICAL = 'critical', 'Crítica'

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberto'
        ACKNOWLEDGED = 'ack', 'Em análise'
        RESOLVED = 'resolved', 'Resolvido'
        FALSE_POSITIVE = 'false_positive', 'Falso positivo'

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    rule = models.CharField(max_length=32, db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    actor_id = models.CharField(max_length=64, blank=True, db_index=True)
    actor_label = models.CharField(max_length=255, blank=True)
    organization_id = models.UUIDField(null=True, blank=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    summary = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=128, unique=True)
    reviewed_by = models.CharField(max_length=64, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.severity}] {self.rule}: {self.summary}'


class BlockedIP(models.Model):
    """Endereço (ou faixa CIDR) bloqueado pela TI na tela de Cibersegurança (CAD-221). Bloqueio vale para todo o sistema."""

    network = models.CharField(max_length=64, unique=True, help_text='IP (203.0.113.7) ou faixa CIDR (203.0.113.0/24).')
    reason = models.CharField(max_length=255)
    created_by = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text='Vazio = até a TI remover.')
    hits = models.PositiveIntegerField(default=0)
    last_hit_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'IP bloqueado'
        verbose_name_plural = 'IPs bloqueados'
