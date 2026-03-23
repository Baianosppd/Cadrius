from django.db import models
from django.conf import settings

class Workflow(models.Model):
    """
    O contêiner principal de uma automação.
    Ex: "Monitorar Prazos Astrea e Notificar no WhatsApp"
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='workflows',
        verbose_name="Proprietário (Escritório)"
    )
    name = models.CharField(max_length=255, verbose_name="Nome da Automação")
    description = models.TextField(blank=True, null=True, verbose_name="Descrição")
    is_active = models.BooleanField(default=True, verbose_name="Ativo?")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Workflow"
        verbose_name_plural = "Workflows"
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Trigger(models.Model):
    """
    O Evento que dá início ao Workflow.
    Pode ser um Webhook do sistema jurídico, um E-mail ou um Agendamento.
    """
    TRIGGER_TYPES = (
        ('WEBHOOK', 'Webhook (Sistema Jurídico/Externo)'),
        ('EMAIL', 'Recebimento de E-mail'),
        ('SCHEDULE', 'Agendamento (Cron)'),
        ('MANUAL', 'Execução Manual'),
    )

    workflow = models.OneToOneField(
        Workflow, 
        on_delete=models.CASCADE, 
        related_name='trigger'
    )
    trigger_type = models.CharField(max_length=50, choices=TRIGGER_TYPES)
    
    # Configurações dinâmicas do gatilho (Ex: qual a URL do webhook ou qual ID da Mailbox)
    config = models.JSONField(
        default=dict, 
        blank=True, 
        help_text="Configurações específicas do gatilho em formato JSON"
    )

    def __str__(self):
        return f"Gatilho: {self.get_trigger_type_display()} -> {self.workflow.name}"


class Action(models.Model):
    """
    Os passos que a automação deve executar após o Gatilho.
    """
    ACTION_TYPES = (
        ('AI_EXTRACTION', 'Extrair Dados com IA (Gemini/ChatGPT)'),
        ('CREATE_TASK', 'Criar Tarefa (Gestão Ágil)'),
        ('SEND_WHATSAPP', 'Enviar Notificação (WhatsApp)'),
        ('SHEETS_INSERT', 'Adicionar Linha (Planilha)'),
    )

    workflow = models.ForeignKey(
        Workflow, 
        on_delete=models.CASCADE, 
        related_name='actions'
    )
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    
    # Define a ordem de execução. Passo 1, Passo 2, Passo 3...
    order = models.PositiveIntegerField(default=1)
    
    # Configuração dinâmica (Ex: ID da Integração do WhatsApp, Prompt da IA, Mapeamento de Colunas)
    config = models.JSONField(
        default=dict, 
        blank=True,
        help_text="Configurações de execução e mapeamento de campos"
    )

    class Meta:
        ordering = ['workflow', 'order']
        unique_together = ('workflow', 'order')

    def __str__(self):
        return f"Passo {self.order}: {self.get_action_type_display()} ({self.workflow.name})"


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