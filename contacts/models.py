"""Quadro de contatos do escritório (CAD-171): clientes, partes, testemunhas, peritos, correspondentes… Base da carteira de clientes e
destinatário das automações. Dados pessoais cifrados; busca por nome (tokens) e por CPF/CNPJ, e-mail e telefone (índice cego).
Consentimento por canal (LGPD): automação só envia WhatsApp/e-mail a quem consentiu e não pediu para sair."""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core.pii import PIIIndexMixin
from core.utils import EncryptedTextField


class Contact(PIIIndexMixin, models.Model):
    BLIND_INDEXES = {
        'document': ('document_bidx', 'contact.document', 'digits'),
        'email': ('email_bidx', 'contact.email', 'text'),
        'phone': ('phone_bidx', 'contact.phone', 'digits'),
    }
    TOKEN_INDEXES = {('name',): ('name_idx', 'contact.name')}

    class Kind(models.TextChoices):
        CLIENT = 'cliente', 'Cliente'
        OPPOSING = 'parte_contraria', 'Parte contrária'
        WITNESS = 'testemunha', 'Testemunha'
        EXPERT = 'perito', 'Perito'
        CORRESPONDENT = 'correspondente', 'Correspondente'
        SUPPLIER = 'fornecedor', 'Fornecedor'
        OTHER = 'outro', 'Outro'

    class PersonType(models.TextChoices):
        PF = 'PF', 'Pessoa física'
        PJ = 'PJ', 'Pessoa jurídica'

    class Source(models.TextChoices):
        MANUAL = 'manual', 'Cadastro manual'
        IMPORT = 'import', 'Importação'
        EXTRACTION = 'extraction', 'Leitura de documento'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='contacts')
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CLIENT, db_index=True)
    person_type = models.CharField(max_length=2, choices=PersonType.choices, default=PersonType.PF)
    name = EncryptedTextField()
    name_idx = models.TextField(blank=True, default='', editable=False)
    document = EncryptedTextField(blank=True, default='')          # CPF ou CNPJ
    document_bidx = models.CharField(max_length=64, null=True, blank=True, editable=False, db_index=True)
    email = EncryptedTextField(blank=True, default='')
    email_bidx = models.CharField(max_length=64, null=True, blank=True, editable=False, db_index=True)
    phone = EncryptedTextField(blank=True, default='')             # com DDD; usado também para WhatsApp
    phone_bidx = models.CharField(max_length=64, null=True, blank=True, editable=False, db_index=True)
    notes = EncryptedTextField(blank=True, default='')
    tags = models.JSONField(default=list, blank=True)
    # consentimento por canal (LGPD art. 7º/8º): quando, de onde veio; opt-out vence o consentimento
    whatsapp_consent = models.BooleanField(default=False)
    email_consent = models.BooleanField(default=False)
    consent_updated_at = models.DateTimeField(null=True, blank=True)
    consent_source = models.CharField(max_length=120, blank=True, default='')
    opted_out = models.BooleanField(default=False)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'document_bidx'], condition=Q(document_bidx__isnull=False),
                                    name='uniq_contact_document_per_org'),
        ]

    def can_receive(self, channel: str) -> bool:
        """Automação pode mandar mensagem por este canal? (consentiu, não saiu e tem o dado)."""
        if self.opted_out:
            return False
        if channel == 'whatsapp':
            return self.whatsapp_consent and bool(self.phone)
        if channel == 'email':
            return self.email_consent and bool(self.email)
        return False
