from django.db import models
from django.conf import settings

from django.db import models
from integrations.models import AppConnection
from accounts.models import Organization

class Workflow(models.Model):
    name = models.CharField(max_length=255)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='workflows')
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    


class Trigger(models.Model):
    """
    O Gatilho: O que faz a automação iniciar.
    Ex: event_type = 'message_received'
    """
    workflow = models.OneToOneField(Workflow, on_delete=models.CASCADE, related_name='trigger')
    connection = models.ForeignKey(AppConnection, on_delete=models.CASCADE, related_name='triggers')
    event_type = models.CharField(max_length=100)
    
    # Guarda como o sistema deve interpretar os dados que chegam
    payload_mapping = models.JSONField(default=dict, blank=True) 

    def __str__(self):
        return f"Trigger: {self.event_type} on {self.connection.name}"

class Action(models.Model):
    ACTION_TYPES = (
        ('WEBHOOK', 'Webhook Externo (Genérico)'),
        ('WHATSAPP_EVOLUTION', 'Enviar WhatsApp (Evolution API)'),
        ('EMAIL_SMTP', 'Enviar E-mail (Nativo)'),
    )
    
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name='actions')
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES, default='WEBHOOK')
    
    # Usado para Webhooks genéricos
    endpoint_url = models.URLField(blank=True, null=True)
    method = models.CharField(max_length=10, default='POST')
    headers = models.JSONField(blank=True, null=True)
    
    # O Template dinâmico. Para WhatsApp, o JSON esperado será: {"number": "{{telefone}}", "text": "Olá {{nome}}"}
    payload_template = models.TextField(help_text="Template JSON com variáveis {{chave}}")

    def __str__(self):
        return f"{self.get_action_type_display()} - {self.workflow.name}"


class ExecutionLog(models.Model):
    """
    Guarda o histórico de cada vez que o fluxo rodou.
    ESSENCIAL para os Dashboards de ROI e para o modelo de ML futuro.
    """
    STATUS_CHOICES = (
        ('SUCCESS', 'Sucesso'),
        ('FAILED', 'Falha'),
        ('PENDING_REVIEW', 'Aguardando Revisão Humana'), # Para a funcionalidade de "Self-Healing/Aprovação"
    )

    workflow = models.ForeignKey(
        Workflow, 
        on_delete=models.CASCADE, 
        related_name='execution_logs'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    
    # O payload inicial que disparou o fluxo (Ex: o JSON do webhook ou texto do e-mail)
    trigger_payload = models.JSONField(null=True, blank=True)
    
    # O resultado final processado
    final_result = models.JSONField(null=True, blank=True)
    
    # Rastreamento de falhas
    error_message = models.TextField(blank=True, null=True)
    
    # Telemetria de Negócios (Quantos segundos esse processo levou vs tempo humano)
    execution_time_ms = models.PositiveIntegerField(
        null=True, blank=True, 
        help_text="Tempo de execução em milissegundos para cálculo de ROI"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workflow', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"[{self.status}] {self.workflow.name} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"