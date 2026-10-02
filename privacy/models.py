import hashlib
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class LegalDocument(models.Model):
    """
    Documento legal VERSIONADO (termos, política, termo de ciência, aviso de IA).
    Depois de publicado o texto é imutável: mudou o texto = nova versão (e novo aceite).
    """

    class Kind(models.TextChoices):
        TERMS = 'terms', 'Termos de Uso'
        PRIVACY = 'privacy', 'Política de Privacidade'
        CIENCIA = 'ciencia', 'Termo de Ciência de Tratamento de Dados'
        AI_NOTICE = 'ai_notice', 'Aviso sobre Inteligência Artificial'
        DPA = 'dpa', 'Cláusula do Controlador / DPA'

    kind = models.CharField(max_length=16, choices=Kind.choices)
    version = models.CharField(max_length=16)
    title = models.CharField(max_length=200)
    content_md = models.TextField()
    content_sha256 = models.CharField(max_length=64, editable=False)
    locale = models.CharField(max_length=8, default='pt-BR')
    requires_reconsent = models.BooleanField(default=True, help_text='Exige novo aceite de quem aceitou versões anteriores.')
    is_current = models.BooleanField(default=False, db_index=True)
    needs_legal_review = models.BooleanField(default=True, help_text='Rascunho: revisão por advogado/DPO pendente.')
    published_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('kind', 'version')
        ordering = ['kind', '-published_at']

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if original.content_md != self.content_md or original.title != self.title:
                raise ValueError('Texto de documento publicado é imutável: crie uma nova versão.')
        self.content_sha256 = hashlib.sha256(self.content_md.encode()).hexdigest()
        super().save(*args, **kwargs)
        if self.is_current:  # só uma versão vigente por tipo
            type(self).objects.filter(kind=self.kind).exclude(pk=self.pk).update(is_current=False)

    def __str__(self):
        return f'{self.get_kind_display()} v{self.version}'


class ConsentRecord(models.Model):
    """
    Prova de ciência/consentimento — APPEND-ONLY. Revogar = novo registro com ``granted=False``.
    ``evidence_sha256`` é o hash do texto exato exibido (prova de qual versão foi aceita).
    """

    class Method(models.TextChoices):
        CHECKBOX = 'checkbox', 'Caixa de seleção'
        CLICK = 'click', 'Clique em aceitar'
        API = 'api', 'API'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='consents')
    user_ref = models.CharField(max_length=64, db_index=True, help_text='ID do utilizador (preservado após anonimização).')
    organization_id = models.UUIDField(null=True, blank=True)
    document = models.ForeignKey(LegalDocument, on_delete=models.PROTECT, related_name='consents')
    purpose = models.CharField(max_length=64, default='essential')
    legal_basis = models.CharField(max_length=32, default='contrato')
    granted = models.BooleanField(default=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent_hash = models.CharField(max_length=16, blank=True)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.CHECKBOX)
    evidence_sha256 = models.CharField(max_length=64)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [models.Index(fields=['user_ref', 'document'])]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('ConsentRecord é append-only.')
        self.user_ref = self.user_ref or (str(self.user_id) if self.user_id else '')
        self.evidence_sha256 = self.document.content_sha256
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('ConsentRecord é append-only.')


class SubprocessorEntry(models.Model):
    """Suboperadores/terceiros que recebem dados (LGPD art. 33 — transferência internacional)."""

    name = models.CharField(max_length=120, unique=True)
    country = models.CharField(max_length=60)
    purpose = models.CharField(max_length=255)
    data_categories = models.JSONField(default=list)
    international_transfer = models.BooleanField(default=True)
    safeguards = models.CharField(max_length=255, blank=True, help_text='Ex.: cláusulas-padrão, DPA assinado.')
    dpa_url = models.URLField(blank=True)
    contract_verified = models.BooleanField(default=False, help_text='DPA/contrato conferido pelo jurídico.')
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.country})'


class DataSubjectRequest(models.Model):
    """Pedido do titular (LGPD art. 18). Prazo padrão de resposta: 15 dias."""

    class Type(models.TextChoices):
        ACCESS = 'access', 'Confirmação/acesso aos dados'
        CORRECTION = 'correction', 'Correção'
        ANONYMIZATION = 'anonymization', 'Anonimização, bloqueio ou eliminação'
        PORTABILITY = 'portability', 'Portabilidade'
        INFO_SHARING = 'info_sharing', 'Informação sobre compartilhamento'
        REVOKE_CONSENT = 'revoke_consent', 'Revogação de consentimento'
        DELETION = 'deletion', 'Eliminação da conta'

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberto'
        IN_PROGRESS = 'in_progress', 'Em atendimento'
        FULFILLED = 'fulfilled', 'Atendido'
        REJECTED = 'rejected', 'Recusado (justificado)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='privacy_requests')
    user_ref = models.CharField(max_length=64, db_index=True)
    organization_id = models.UUIDField(null=True, blank=True)
    type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    notes = models.TextField(blank=True)
    opened_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField()
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.CharField(max_length=64, blank=True)
    resolution = models.TextField(blank=True)

    class Meta:
        ordering = ['-opened_at']

    def save(self, *args, **kwargs):
        if not self.due_at:
            self.due_at = (self.opened_at or timezone.now()) + timedelta(days=15)
        super().save(*args, **kwargs)

    @property
    def overdue(self) -> bool:
        return self.status in (self.Status.OPEN, self.Status.IN_PROGRESS) and timezone.now() > self.due_at


class OrganizationOffboarding(models.Model):
    """RNE-013: ao cancelar, dados mantidos 30 dias para recuperação e depois eliminados."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Em período de recuperação'
        CANCELLED = 'cancelled', 'Cancelado (conta recuperada)'
        PURGED = 'purged', 'Eliminado'

    organization_id = models.UUIDField(db_index=True)
    organization_name = models.CharField(max_length=255)
    requested_by = models.CharField(max_length=64)
    requested_at = models.DateTimeField(default=timezone.now)
    purge_after = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    purged_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-requested_at']
