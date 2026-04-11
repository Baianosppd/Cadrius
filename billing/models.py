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