# billing/decorators.py (Cria este ficheiro)
from functools import wraps
from django.utils import timezone
from billing.models import AIUsageLog
from workflows.models import Workflow

def check_quota_limit(func):
    """
    Middleware/Decorator para intercetar a task assíncrona.
    Verifica se a Organização ainda tem créditos antes de executar.
    """
    @wraps(func)
    def wrapper(workflow_id, payload, *args, **kwargs):
        try:
            workflow = Workflow.objects.select_related('organization__plan').get(id=workflow_id)
            org = workflow.organization
            
            # Obtém o contador do mês atual
            month_start = timezone.now().replace(day=1)
            usage, created = AIUsageLog.objects.get_or_create(
                organization=org, 
                billing_cycle_month=month_start
            )
            
            # Verifica se atingiu o limite do plano
            if usage.extractions_count >= org.plan.max_ai_extractions:
                from workflows.models import ExecutionLog
                # Interrompe o ciclo e regista a falha comercial
                ExecutionLog.objects.create(
                    workflow=workflow,
                    status='QUOTA_EXCEEDED',
                    error_message='O limite de execuções mensais do plano foi atingido.',
                    trigger_payload=payload
                )
                return False  # Aborta a execução silenciosamente

            # Se tem saldo, executa a task real
            return func(workflow_id, payload, *args, **kwargs)
            
        except Workflow.DoesNotExist:
            return False

    return wrapper