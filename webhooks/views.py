import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from webhooks.models import WebhookTrigger
from django_q.tasks import async_task 

@csrf_exempt  
@require_POST 
def dynamic_webhook_receiver(request, identifier):
    """
    Endpoint que recebe os payloads de fora: /api/webhooks/<identifier>/
    """
    # 1. Validar se é um JSON válido
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Payload JSON inválido. O Cadrius apenas aceita JSON."}, status=400)

    # 2. Buscar o Trigger usando select_related para otimizar a consulta no banco
    try:
        trigger = WebhookTrigger.objects.select_related('workflow__organization').get(identifier=identifier)
    except WebhookTrigger.DoesNotExist:
        return JsonResponse({"error": "Webhook não encontrado ou identificador inválido."}, status=404)

    workflow = trigger.workflow
    organization = workflow.organization

    # 3. Validar estado do Workflow e da Organização (Freio B2B)
    if not workflow.is_active:
        return JsonResponse({"error": "Este workflow está desativado no painel."}, status=400)
        
    if not organization.is_active:
        return JsonResponse({"error": "A organização associada está suspensa ou inadimplente."}, status=403)

    # 4. Preparar dados para envio à fila de execução (Django-Q)
 
    async_task('tasks.tasks.execute_workflow_pipeline', workflow.id, payload)

    # 5. Responder rápido (Non-blocking) para não dar Timeout na API externa
    return JsonResponse({
        "message": "Webhook recebido com sucesso e enfileirado para processamento.",
        "workflow_id": workflow.id
    }, status=202)