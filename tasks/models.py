# julliodutra/cadrius/cadrius-d2664e7d9d3cdaaeb4729d29c9fafb13438707c0/integrations/models.py

from django.db import models
# REMOVIDO: from emails.models import EmailMessage 
from django.utils import timezone

class IntegrationStatus(models.TextChoices):
    SUCCESS = 'SUCCESS', 'Sucesso'
    FAILED = 'FAILED', 'Falha na Integração'
    PENDING = 'PENDING', 'Pendente de Execução'
    RETRIED = 'RETRIED', 'Tentativa de Retry'

# --- NOVO MODELO PARA CONFIGURAÇÃO DE INTEGRAÇÕES EXTERNAS ---
class IntegrationConfig(models.Model):
    """
    Configurações centralizadas de APIs externas (Trello, Telegram, Projuris),
    substituindo variáveis de ambiente.
    """
    name = models.CharField(max_length=100, unique=True, verbose_name="Nome da Configuração")
    
    # TRELLO (Para Projuris/Card Creation)
    trello_api_key = models.CharField(max_length=255, blank=True, verbose_name="Trello API Key")
    trello_api_token = models.CharField(max_length=255, blank=True, verbose_name="Trello API Token")
    trello_list_id = models.CharField(max_length=255, blank=True, verbose_name="Trello List ID Padrão")
    
    # TELEGRAM (Para Notificações)
    telegram_bot_token = models.CharField(max_length=255, blank=True, verbose_name="Telegram Bot Token")
    telegram_chat_id = models.CharField(max_length=255, blank=True, verbose_name="Telegram Chat ID Padrão")
    
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Configuração de Integração Externa"
        verbose_name_plural = "Configurações de Integração Externa"

    def __str__(self):
        return self.name

class IntegrationLog(models.Model):
    """
    Registra o log de chamadas para serviços externos (Trello, Telegram).
    """
    SERVICE_CHOICES = (
        ('TRELLO', 'Trello Card Creation'),
        ('TELEGRAM', 'Telegram Notification'),
    )
    
    # Correção Circular: Usando string de referência 'emails.EmailMessage'
    email_message = models.ForeignKey(
        'emails.EmailMessage', 
        on_delete=models.CASCADE, 
        related_name='integration_logs',
        help_text="Email que acionou esta integração."
    )
    
    service = models.CharField(max_length=50, choices=SERVICE_CHOICES)
    status = models.CharField(max_length=20, choices=IntegrationStatus.choices, default=IntegrationStatus.PENDING)
    
    # Dados da requisição
    request_data = models.JSONField(null=True, blank=True, help_text="Payload enviado ao serviço externo.")
    
    # Dados da resposta
    response_code = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True, help_text="Resposta recebida do serviço externo.")
    
    attempted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Log de Integração"
        verbose_name_plural = "Logs de Integração"
        # Thales: Permite a busca rápida pelo email e serviço.
        indexes = [
            models.Index(fields=['email_message', 'service', 'status']),
        ]
    
    def __str__(self):
        return f'[{self.get_service_display()}] {self.status} - Email: {self.email_message.id}'