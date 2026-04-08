from django.db import models

from integrations.models import AppConnection


class Workflow(models.Model):
    name = models.CharField(max_length=255)
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

    webhook_identifier = models.CharField(
        max_length=128,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text='Chave única em POST /api/webhooks/<identifier>/',
    )

    def __str__(self):
        return f"Trigger: {self.event_type} on {self.connection.name}"


class Action(models.Model):
    """
    A Ação: O que o sistema deve fazer quando o gatilho disparar.
    Ex: action_type = 'create_card'
    """

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name='actions')
    connection = models.ForeignKey(AppConnection, on_delete=models.CASCADE, related_name='actions')
    action_type = models.CharField(max_length=100)

    # A ordem de execução (caso o workflow tenha múltiplas ações: Passo 1, Passo 2...)
    order = models.PositiveIntegerField(default=1)

    # Guarda o "molde" do JSON que será enviado para a ferramenta de destino
    payload_template = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Action {self.order}: {self.action_type} on {self.connection.name}"


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
