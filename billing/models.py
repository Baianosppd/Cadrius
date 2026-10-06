from django.db import models

class SubscriptionPlan(models.Model):
    """ Os pacotes que o Cadrius vende """
    TIER_CHOICES = (
        ('FREE', 'Trial Gratuito'),
        ('START', 'Plano Start'),
        ('PRO', 'Plano Profissional'),
        ('ENTERPRISE', 'Plano Enterprise'),
    )
    
    name = models.CharField(max_length=50, verbose_name="Nome do Plano")
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, unique=True)
    price_brl = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Preço (R$)")
    
    # Limites do Plano (O motor de Upsell)
    max_users = models.IntegerField(default=1, verbose_name="Limite de Utilizadores")
    max_ai_extractions = models.IntegerField(default=100, verbose_name="Extrações IA por Mês")
    
    # Adicionado para corrigir o erro do Admin
    is_active = models.BooleanField(default=True, verbose_name="Plano Ativo")
    
    def __str__(self):
        return f"{self.name} (R$ {self.price_brl})"

class AIUsageLog(models.Model):
    """ O 'Relógio de Luz' para medir gastos com as APIs """
   
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='ai_usage')
    billing_cycle_month = models.DateField(verbose_name="Mês de Faturação")
    extractions_count = models.IntegerField(default=0, verbose_name="Contagem de Extrações")

    class Meta:
        unique_together = ('organization', 'billing_cycle_month')


class MemberCreditUsage(models.Model):
    """Créditos consumidos por membro do escritório em cada mês."""

    membership = models.ForeignKey(
        'accounts.OrganizationMembership',
        on_delete=models.CASCADE,
        related_name='credit_usage',
    )
    billing_cycle_month = models.DateField(verbose_name="Mês de Faturação")
    credits_used = models.PositiveIntegerField(default=0, verbose_name="Créditos usados")

    class Meta:
        unique_together = ('membership', 'billing_cycle_month')
        verbose_name = "Uso de créditos do membro"
        verbose_name_plural = "Uso de créditos dos membros"

    def __str__(self):
        return f"{self.membership_id} {self.billing_cycle_month}: {self.credits_used}"


class CreditPack(models.Model):
    """Pacote de créditos avulsos à venda (CAD-119). Os créditos comprados valem 12 meses e são usados DEPOIS dos do plano."""

    name = models.CharField(max_length=60)
    credits = models.PositiveIntegerField()
    price_brl = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['price_brl']

    def __str__(self):
        return f'{self.name} ({self.credits} créditos, R$ {self.price_brl})'


class CreditLot(models.Model):
    """Lote de créditos comprados por um escritório. ``stripe_session_id`` único = compra idempotente (webhook reenviado não duplica)."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='credit_lots')
    credits_total = models.PositiveIntegerField()
    credits_remaining = models.PositiveIntegerField()
    expires_at = models.DateTimeField()
    stripe_session_id = models.CharField(max_length=100, unique=True)
    amount_paid_cents = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['expires_at', 'id']


# ----------------------------------------------------------------------------- área administrativa do financeiro (CAD-160)
class Promotion(models.Model):
    """Promoção/cupom aplicável na assinatura de um plano. O desconto é refletido no Stripe via Coupon (criado sob demanda)."""

    class Kind(models.TextChoices):
        PERCENT = 'percent', 'Percentual (%)'
        AMOUNT = 'amount', 'Valor fixo (R$)'
        TRIAL = 'trial', 'Dias extras de teste'           # CAD-224: valor = dias; não gera desconto no Stripe

    class Duration(models.TextChoices):
        ONCE = 'once', 'Só na primeira cobrança'
        REPEATING = 'repeating', 'Por N meses'
        FOREVER = 'forever', 'Para sempre'

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    duration = models.CharField(max_length=10, choices=Duration.choices, default=Duration.ONCE)
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    plan_tiers = models.JSONField(default=list, blank=True, help_text='Ex.: ["START","PRO"]. Vazio = todos os planos.')
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    redemptions_count = models.PositiveIntegerField(default=0, editable=False)
    is_active = models.BooleanField(default=True)
    stripe_coupon_id = models.CharField(max_length=64, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} ({self.name})'


class PromotionRedemption(models.Model):
    """Uso de uma promoção por um escritório (um por promoção/escritório)."""

    promotion = models.ForeignKey(Promotion, on_delete=models.CASCADE, related_name='redemptions')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='promotion_redemptions')
    stripe_session_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['promotion', 'organization'], name='uniq_promo_per_org')]


class BillingNotice(models.Model):
    """Informe do financeiro mostrado no app (ex.: reajuste de preços, manutenção de cobrança, promoção). Segmentável."""

    class Severity(models.TextChoices):
        INFO = 'info', 'Informativo'
        WARN = 'warn', 'Atenção'
        DANGER = 'danger', 'Urgente'

    title = models.CharField(max_length=120)
    body = models.TextField()
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.INFO)
    audience_tiers = models.JSONField(default=list, blank=True, help_text='Vazio = todos os planos.')
    audience_statuses = models.JSONField(default=list, blank=True, help_text='Ex.: ["trialing","past_due"]. Vazio = todos.')
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class CreditWeight(models.Model):
    """Quantos créditos cada operação de IA consome (ajustável sem deploy). Ver docs/ANALISE_PRECOS_PLANOS.md §3."""

    operation = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=80)
    credits = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['operation']

    def __str__(self):
        return f'{self.operation}: {self.credits}'


class PlanPriceHistory(models.Model):
    """Histórico de alterações de preço/limites dos planos (quem, quando, de/para)."""

    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name='history')
    old_price = models.DecimalField(max_digits=10, decimal_places=2)
    new_price = models.DecimalField(max_digits=10, decimal_places=2)
    old_credits = models.IntegerField()
    new_credits = models.IntegerField()
    changed_by = models.CharField(max_length=64, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']


class Payment(models.Model):
    """Recebimento confirmado pelo Stripe (CAD-170) — base do setor Fiscal (notas fiscais) e dos relatórios ao contador.

    Idempotente por ``stripe_id``: assinatura = id da *invoice* (1ª cobrança e renovações), pacote de créditos = id da sessão de checkout.
    """

    class Kind(models.TextChoices):
        SUBSCRIPTION = 'subscription', 'Assinatura'
        CREDIT_PACK = 'credit_pack', 'Pacote de créditos'

    class InvoiceStatus(models.TextChoices):
        PENDING = 'pending', 'NF pendente'
        PROCESSING = 'processing', 'NFS-e em processamento'
        ISSUED = 'issued', 'NF emitida'
        ERROR = 'error', 'NFS-e com erro'
        CANCELED = 'canceled', 'NF cancelada'
        NOT_REQUIRED = 'not_required', 'Sem NF'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.PROTECT, related_name='payments')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    description = models.CharField(max_length=200, blank=True, default='')
    amount_cents = models.PositiveIntegerField()
    paid_at = models.DateTimeField(db_index=True)
    stripe_id = models.CharField(max_length=100, unique=True)
    invoice_status = models.CharField(max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.PENDING, db_index=True)
    invoice_number = models.CharField(max_length=60, blank=True, default='')
    invoice_issued_at = models.DateField(null=True, blank=True)
    invoice_note = models.CharField(max_length=255, blank=True, default='')
    # CAD-175 — fase 2 do Fiscal: emissão da NFS-e pelo emissor (Focus NFe), com conferência antes
    nfse_ref = models.CharField(max_length=60, blank=True, default='', db_index=True)
    nfse_url = models.URLField(max_length=500, blank=True, default='')
    nfse_error = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_at', '-id']


class FiscalObligation(models.Model):
    """Obrigação fiscal da Cadrius (empresa) — fase 3 do Fiscal (CAD-175). Datas e regras editáveis: [VALIDAR com o contador]."""

    class Periodicity(models.TextChoices):
        MONTHLY = 'mensal', 'Mensal'
        ANNUAL = 'anual', 'Anual'

    class Adjust(models.TextChoices):
        BEFORE = 'antecipa', 'Antecipa para o dia útil anterior'
        AFTER = 'posterga', 'Posterga para o próximo dia útil'
        LAST_BUSINESS = 'ultimo_util', 'Último dia útil do mês'

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True, default='')
    periodicity = models.CharField(max_length=6, choices=Periodicity.choices, default=Periodicity.MONTHLY)
    due_day = models.PositiveSmallIntegerField(default=20)          # dia do mês seguinte à competência (mensal) ou do mês (anual)
    due_month = models.PositiveSmallIntegerField(default=3)         # só anual: mês do vencimento
    adjust = models.CharField(max_length=12, choices=Adjust.choices, default=Adjust.BEFORE)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_day', 'code']


class FiscalObligationDone(models.Model):
    obligation = models.ForeignKey(FiscalObligation, on_delete=models.CASCADE, related_name='done')
    competence = models.CharField(max_length=7)                     # AAAA-MM (mensal) ou AAAA (anual)
    done_by = models.ForeignKey('accounts.CustomUser', null=True, on_delete=models.SET_NULL, related_name='+')
    done_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['obligation', 'competence'], name='uniq_obligation_competence')]
