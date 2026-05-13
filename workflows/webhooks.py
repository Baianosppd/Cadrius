"""
Endpoints HTTP públicos ligados a workflows (disparos externos, gateways, etc.).
"""
import logging

from django_q.tasks import async_task
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Trigger

logger = logging.getLogger(__name__)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def catch_webhook_event(request, token):
    """
    POST com o corpo JSON do sistema externo; ``token`` (UUID na URL) corresponde a
    ``Trigger.webhook_token``. Enfileira ``execute_workflow_pipeline`` quando o fluxo
    e a organização estão ativos.
    """
    try:
        trigger = Trigger.objects.select_related("workflow__organization").get(
            webhook_token=token
        )
    except Trigger.DoesNotExist:
        return Response(
            {"detail": "Token inválido ou gatilho inexistente."},
            status=status.HTTP_404_NOT_FOUND,
        )

    workflow = trigger.workflow
    if not workflow.is_active or not workflow.organization.is_active:
        return Response(
            {"detail": "Workflow ou organização indisponível."},
            status=status.HTTP_410_GONE,
        )

    payload = request.data
    async_task("workflows.tasks.execute_workflow_pipeline", workflow.id, payload)
    logger.info(
        "Webhook externo enfileirado: workflow_id=%s trigger_id=%s",
        workflow.id,
        trigger.id,
    )
    return Response(
        {"status": "success", "message": "Orquestração enfileirada!"},
        status=status.HTTP_202_ACCEPTED,
    )


class WebhookReceiverView(APIView):
    """
    Gateway: recebe disparos da Evolution API (WhatsApp).
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "webhook"

    def post(self, request, connection_id):
        payload = request.data

        evento = payload.get("event")

        if evento == "messages.upsert":
            dados_mensagem = payload.get("data", {})
            numero_remetente = dados_mensagem.get("key", {}).get("remoteJid")
            mensagem = dados_mensagem.get("message", {})
            texto = mensagem.get("conversation") or mensagem.get(
                "extendedTextMessage", {}
            ).get("text")

            if numero_remetente and texto:
                logger.info(
                    "[WhatsApp Cadrius] connection=%s de=%s",
                    connection_id,
                    numero_remetente,
                )

        return Response({"status": "sucesso"}, status=status.HTTP_202_ACCEPTED)
