# billing/decorators.py (Cria este ficheiro)
from functools import wraps
from billing.credits import check_credit_available
from workflows.models import Workflow

def check_quota_limit(func):
    """
    Middleware/Decorator para intercetar a task assíncrona.
    Verifica se a Organização (e o membro que disparou, se houver cota) ainda tem créditos.
    """
    @wraps(func)
    def wrapper(workflow_id, payload, user_id=None, *args, **kwargs):
        try:
            workflow = Workflow.objects.select_related('organization__plan').get(id=workflow_id)
            org = workflow.organization

            ok, message = check_credit_available(org, user_id=user_id)
            if not ok:
                from workflows.models import ExecutionLog
                # Interrompe o ciclo e regista a falha comercial
                ExecutionLog.objects.create(
                    workflow=workflow,
                    status='QUOTA_EXCEEDED',
                    error_message=message,
                    trigger_payload=payload
                )
                return False  # Aborta a execução silenciosamente

            # Se tem saldo, executa a task real
            return func(workflow_id, payload, user_id=user_id, *args, **kwargs)
            
        except Workflow.DoesNotExist:
            return False

    return wrapper
