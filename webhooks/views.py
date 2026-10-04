import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle
from core.queue import RETRY_AFTER_SECONDS, QueueUnavailable, enqueue

from integrations.models import AppConnection
from workflows.models import Trigger

logger = logging.getLogger(__name__)

class WebhookReceiverView(APIView):
    """
    Endpoint Gateway: Recebe POSTs externos e injeta no motor de hiperautomação assincronamente.
    """
    authentication_classes = [] # Aberto à internet (robôs não fazem login)
    permission_classes = []     # A segurança é feita pelo UUID da URL
    # Endpoint público: sem limite, qualquer um podia enfileirar tarefas sem fim (DoS do worker).
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'webhook'

    def post(self, request, connection_id):
        try:
            # 1. Valida se a porta (UUID) pertence a um cliente real do nosso SaaS
            connection = AppConnection.objects.get(id=connection_id)

            # 2. Descobre que gatilhos (Triggers) estão ligados a esta porta
            triggers = Trigger.objects.filter(connection=connection)

            if not triggers.exists():
                return Response({"message": "Recebido, mas não há automações ligadas."}, status=status.HTTP_200_OK)

            # 3. Captura o payload (JSON) cru que o sistema externo enviou
            payload = request.data
            logger.info(f"📥 [Webhook] Dados recebidos na conexão {connection_id}.")

            # 4. Injeta os dados na FILA ASSÍNCRONA (Músculos do Django-Q)
            for trigger in triggers:
                workflow = trigger.workflow
                
                # Validação de Segurança (Freio B2B que tinhas feito muito bem!)
                if workflow.is_active and workflow.organization.is_active:
                    # 🚀 Lançamos para a fila em vez de congelar a resposta
                    enqueue(
                        'workflows.tasks.execute_workflow_pipeline',
                        workflow.id,
                        payload,
                        connection.user_id,
                    )
                    logger.info(f"⚡ [Webhook] Workflow {workflow.id} enfileirado com sucesso.")

            # 5. Responde em milissegundos (HTTP 202 Accepted) para evitar Timeouts
            return Response({"status": "success", "message": "Orquestração enfileirada!"}, status=status.HTTP_202_ACCEPTED)

        except QueueUnavailable:
            # Origem externa deve repetir a entrega: 503 + Retry-After (não 500).
            response = Response({"error": "Fila indisponível, tente novamente."},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
            response["Retry-After"] = str(RETRY_AFTER_SECONDS)
            return response
        except AppConnection.DoesNotExist:
            logger.warning(f"⚠️ Tentativa de Webhook fantasma. ID: {connection_id}")
            return Response({"error": "Gateway não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"❌ Erro crítico no Webhook: {e}")
            return Response({"error": "Falha no motor de processamento."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)