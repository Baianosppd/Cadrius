from django.db import models
from django.conf import settings

class IntegrationStatus(models.TextChoices):
    SUCCESS = 'SUCCESS', 'Sucesso'
    FAILED = 'FAILED', 'Falha na Integração'
    PENDING = 'PENDING', 'Pendente de Execução'
    RETRIED = 'RETRIED', 'Tentativa de Retry'

class AppConnection(models.Model):
    """
    Armazena credenciais de forma genérica para qualquer integração
    (WhatsApp, Sheets, Sistemas Jurídicos, Trello, etc).
    """
    APP_CHOICES = (
        ('WHATSAPP', 'WhatsApp (API Meta/Evolution)'),
        ('SHEETS', 'Google Sheets'),
        ('CLICKUP', 'ClickUp'),
        ('TRELLO', 'Trello'),
        ('TELEGRAM', 'Telegram'),
        ('ASTREA', 'Astrea (Sistema Jurídico)'),
        ('WEBHOOK', 'Webhook Customizado'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='connections', 
        verbose_name="Proprietário"
    )
    
    name = models.CharField(max_length=100, verbose_name="Nome da Conexão (ex: WhatsApp do Suporte)")
    app_name = models.CharField(max_length=50, choices=APP_CHOICES, verbose_name="Aplicativo")
    
    credentials = models.JSONField(
        default=dict, 
        help_text="Credenciais no formato JSON. (Deverão ser encriptadas no banco!)"
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Conexão de App"
        verbose_name_plural = "Conexões de Apps"
        # Impede que o utilizador crie duas ligações com o mesmo nome exato
        unique_together = ('user', 'name')

    def __str__(self):
        return f"{self.name} ({self.get_app_name_display()})"


class IntegrationLog(models.Model):
    """
    Registos de chamadas para serviços externos.
    
    """
    # Liga o log à conexão que foi utilizada (para sabermos de onde veio o erro)
    connection = models.ForeignKey(
        AppConnection,
        on_delete=models.SET_NULL,
        null=True,
        related_name='logs'
    )
    
    status = models.CharField(max_length=20, choices=IntegrationStatus.choices, default=IntegrationStatus.PENDING)
    
    # Dados da requisição e resposta
    request_data = models.JSONField(null=True, blank=True, help_text="Payload enviado ao serviço externo.")
    response_code = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True, help_text="Resposta recebida do serviço externo.")
    
    error_message = models.TextField(null=True, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Log de Integração"
        verbose_name_plural = "Logs de Integração"
        ordering = ['-attempted_at']
        indexes = [
            models.Index(fields=['connection', 'status']),
        ]
    
    def __str__(self):
        conn_name = self.connection.name if self.connection else "Desconhecido"
        return f'[{conn_name}] {self.status} - {self.attempted_at.strftime("%d/%m %H:%M")}'