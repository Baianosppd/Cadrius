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
    Gatilho de entrada: tipo fixo (controle estático) + conexão genérica + template de payload.
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
    app_connection = models.ForeignKey(
        'integrations.AppConnection',
        on_delete=models.PROTECT,
        related_name='workflow_triggers',
        verbose_name="Conexão de app",
    )
    payload_template = models.JSONField(
        default=dict,
        blank=True,
        help_text="Template / metadados de o que receber ou enviar neste gatilho (sem acoplar a um vendor).",
    )

    def __str__(self):
        return f"Gatilho: {self.get_trigger_type_display()} -> {self.workflow.name}"


class Action(models.Model):
    """
    Passo de saída: tipo fixo (controle estático) + conexão genérica + template de payload.
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
    order = models.PositiveIntegerField(
        default=1,
        help_text="Ordem no pipeline.",
    )
    action_type = models.CharField(max_length=50, choices=ACTION_TYPES)
    app_connection = models.ForeignKey(
        'integrations.AppConnection',
        on_delete=models.PROTECT,
        related_name='workflow_actions',
        verbose_name="Conexão de app",
    )
    payload_template = models.JSONField(
        default=dict,
        blank=True,
        help_text="Template de o que enviar/receber neste passo (mapeamentos, corpo da mensagem, etc.).",
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
        ('PENDING_REVIEW', 'Aguardando Revisão Humana'),  # Para a funcionalidade de "Self-Healing/Aprovação"
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
        null=True,
        blank=True,
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
