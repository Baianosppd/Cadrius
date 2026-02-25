from django.db import models
from emails.models import EmailMessage # Importa o modelo base de Jullio
from django.utils import timezone
from django.contrib.auth import get_user_model


User = get_user_model() # NOVO

class IntegrationStatus(models.TextChoices):
    SUCCESS = 'SUCCESS', 'Sucesso'
    FAILED = 'FAILED', 'Falha na Integração'
    PENDING = 'PENDING', 'Pendente de Execução'
    RETRIED = 'RETRIED', 'Tentativa de Retry'
    
    
class IntegrationConfig(models.Model):
    """
    Configurações centralizadas de APIs externas (Trello, Telegram),
    substituindo variáveis de ambiente.
    
    """
    
    # NOVO CAMPO: Liga a config ao usuário/cliente
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='integration_configs', 
        verbose_name="Proprietário"
    )
    
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
    
    email_message = models.ForeignKey(
            'emails.EmailMessage', # Usando string reference
            on_delete=models.CASCADE, 
            related_name='integration_logs_ext', # Nome exclusivo para evitar o clash
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