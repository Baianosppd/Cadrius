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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['expires_at', 'id']
