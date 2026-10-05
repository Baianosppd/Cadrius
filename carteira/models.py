"""Carteira de clientes e financeiro do escritório (CAD-175, fase F).

- **Oportunidade** (funil de captação): do primeiro contato ao contrato fechado (ou perdido, com o motivo).
- **Contrato de honorários**: à vista, parcelado, mensal (recorrente), êxito ou misto; gera as parcelas a receber.
- **Lançamento a receber**: cada parcela/cobrança. Pode virar boleto/Pix no Asaas; o webhook do Asaas dá baixa sozinho.
- **Despesa**: custas, diligências, perícia… por processo/cliente (reembolsável ou do escritório) — base da margem por cliente.

Valores em centavos (inteiros). Observações cifradas em repouso. Tudo isolado por escritório.
"""
from django.conf import settings
from django.db import models

from core.utils import EncryptedTextField


class Opportunity(models.Model):
    class Stage(models.TextChoices):
        NEW = 'novo', 'Novo contato'
        QUALIFY = 'qualificacao', 'Entendendo o caso'
        MEETING = 'reuniao', 'Reunião marcada'
        PROPOSAL = 'proposta', 'Proposta enviada'
        WON = 'ganho', 'Contrato fechado'
        LOST = 'perdido', 'Não fechou'

    class Source(models.TextChoices):
        REFERRAL = 'indicacao', 'Indicação'
        SITE = 'site', 'Site / blog'
        SOCIAL = 'redes', 'Redes sociais'
        GOOGLE = 'google', 'Google / Perfil da empresa'
        CLIENT = 'cliente', 'Cliente da casa'
        OTHER = 'outro', 'Outro'

    OPEN_STAGES = (Stage.NEW, Stage.QUALIFY, Stage.MEETING, Stage.PROPOSAL)

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='opportunities')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.CASCADE, related_name='opportunities')
    title = models.CharField(max_length=160)
    area = models.CharField(max_length=40, blank=True, default='')
    stage = models.CharField(max_length=14, choices=Stage.choices, default=Stage.NEW, db_index=True)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.OTHER)
    value_cents = models.PositiveBigIntegerField(default=0)            # honorários estimados
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    next_action = models.CharField(max_length=160, blank=True, default='')
    next_action_at = models.DateField(null=True, blank=True)
    lost_reason = models.CharField(max_length=200, blank=True, default='')
    notes = EncryptedTextField(blank=True, default='')
    stage_changed_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['organization', 'stage'])]


class FeeAgreement(models.Model):
    class Kind(models.TextChoices):
        UPFRONT = 'avista', 'À vista'
        INSTALLMENTS = 'parcelado', 'Parcelado'
        MONTHLY = 'mensal', 'Mensal (partido/recorrente)'
        SUCCESS = 'exito', 'Êxito (% do proveito)'
        MIXED = 'misto', 'Entrada + êxito'

    class Status(models.TextChoices):
        ACTIVE = 'ativo', 'Ativo'
        DONE = 'encerrado', 'Encerrado'
        CANCELED = 'cancelado', 'Cancelado'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='fee_agreements')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT, related_name='fee_agreements')
    case = models.ForeignKey('research.MonitoredCase', null=True, blank=True, on_delete=models.SET_NULL, related_name='fee_agreements')
    opportunity = models.ForeignKey(Opportunity, null=True, blank=True, on_delete=models.SET_NULL, related_name='agreements')
    title = models.CharField(max_length=160)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    total_cents = models.PositiveBigIntegerField(default=0)          # valor fixo (à vista/parcelado/entrada) ou da mensalidade
    installments = models.PositiveSmallIntegerField(default=1)       # nº de parcelas (ou de meses, no mensal)
    first_due = models.DateField(null=True, blank=True)
    success_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)   # % do proveito econômico (êxito)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    notes = EncryptedTextField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class Receivable(models.Model):
    class Status(models.TextChoices):
        OPEN = 'aberto', 'Em aberto'
        PAID = 'pago', 'Pago'
        CANCELED = 'cancelado', 'Cancelado'

    class Method(models.TextChoices):
        PIX = 'pix', 'Pix'
        BOLETO = 'boleto', 'Boleto'
        CARD = 'cartao', 'Cartão'
        TRANSFER = 'transferencia', 'Transferência'
        CASH = 'dinheiro', 'Dinheiro'
        OTHER = 'outro', 'Outro'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='receivables')
    agreement = models.ForeignKey(FeeAgreement, null=True, blank=True, on_delete=models.CASCADE, related_name='receivables')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.PROTECT, related_name='receivables')
    case = models.ForeignKey('research.MonitoredCase', null=True, blank=True, on_delete=models.SET_NULL, related_name='receivables')
    description = models.CharField(max_length=200)
    amount_cents = models.PositiveBigIntegerField()
    due_date = models.DateField(db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    paid_at = models.DateField(null=True, blank=True)
    paid_cents = models.PositiveBigIntegerField(default=0)
    method = models.CharField(max_length=14, choices=Method.choices, blank=True, default='')
    asaas_id = models.CharField(max_length=40, blank=True, default='', db_index=True)
    payment_url = models.URLField(max_length=500, blank=True, default='')
    notes = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date', 'id']
        indexes = [models.Index(fields=['organization', 'status', 'due_date'])]


class Expense(models.Model):
    class Category(models.TextChoices):
        COURT = 'custas', 'Custas processuais'
        ERRAND = 'diligencia', 'Diligência / correspondente'
        EXPERT = 'pericia', 'Perícia / assistente técnico'
        TRAVEL = 'deslocamento', 'Deslocamento'
        COPIES = 'copias', 'Cópias / cartório'
        OFFICE = 'escritorio', 'Despesa do escritório'
        OTHER = 'outros', 'Outros'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='expenses')
    contact = models.ForeignKey('contacts.Contact', null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses')
    case = models.ForeignKey('research.MonitoredCase', null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses')
    description = models.CharField(max_length=200)
    category = models.CharField(max_length=14, choices=Category.choices, default=Category.COURT)
    amount_cents = models.PositiveBigIntegerField()
    date = models.DateField(db_index=True)
    reimbursable = models.BooleanField(default=False)       # o cliente reembolsa (vira lançamento a receber)
    reimbursement = models.OneToOneField(Receivable, null=True, blank=True, on_delete=models.SET_NULL, related_name='expense')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']


class AsaasEvent(models.Model):
    """Eventos do webhook do Asaas já processados (entrega "pelo menos uma vez" → idempotência pelo id do evento)."""
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='+')
    event_id = models.CharField(max_length=80)
    event = models.CharField(max_length=40)
    payment_id = models.CharField(max_length=40, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'event_id'], name='uniq_asaas_event')]
