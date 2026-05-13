"""
Endpoints HTTP públicos ligados a workflows (disparos externos, gateways, etc.).
"""
import json
import logging

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Trigger
from .tasks import execute_workflow_pipeline
from .throttles import WebhookCatchRateThrottle

logger = logging.getLogger(__name__)


def extract_webhook_request_body(request):
    """
    Extrai o corpo do POST: ``request.data`` (parse do DRF consoante ``Content-Type`` /
    parsers configurados) ou ``request.body`` quando o corpo não cai nos parsers habituais.
    O resultado deve ser JSON-serializável para ``ExecutionLog.trigger_payload``.
    """
    content_type = (request.META.get("CONTENT_TYPE") or "").split(";")[0].strip().lower()
    raw = getattr(request, "body", b"") or b""

    parsed_by_drf = content_type.startswith(
        ("application/json", "application/x-www-form-urlencoded", "multipart/")
    ) or (not content_type and raw)

    if parsed_by_drf:
        data = request.data
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return dict(data)
        if hasattr(data, "lists"):
            return {k: (v[0] if len(v) == 1 else v) for k, v in data.lists()}

    if not raw:
        return {}

    text = raw.decode(getattr(request, "encoding", None) or "utf-8", errors="replace")
    if "json" in content_type or raw.lstrip().startswith((b"{", b"[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_invalid_json": text}
    return {"_body": text}


@api_view(["POST"])
@throttle_classes([WebhookCatchRateThrottle])
@authentication_classes([])
@permission_classes([AllowAny])
def catch_webhook_event(request, token):
    """
    POST com o corpo JSON do sistema externo; ``token`` (UUID na URL) corresponde a
    ``Trigger.webhook_token``. Só aceita gatilho cujo workflow está ativo; caso contrário **404**.

    Cria o ``ExecutionLog`` (via ``execute_workflow_pipeline``: quota + ``PENDING`` + payload),
    enfileira ``process_workflow_execution`` (runner CAD-001) e responde **202** com
    ``{"status": "accepted", "log_id": …}``.

    Rate limit DRF (``webhook_catch``): mitiga abuso se o URL com token vazar.
    """
    try:
        trigger = Trigger.objects.select_related("workflow__organization").get(
            webhook_token=token,
            workflow__is_active=True,
        )
    except Trigger.DoesNotExist:
        return Response(
            {"detail": "Token inválido, gatilho inexistente ou workflow inativo."},
            status=status.HTTP_404_NOT_FOUND,
        )

    workflow = trigger.workflow
    payload = extract_webhook_request_body(request)
    result = execute_workflow_pipeline(workflow.id, payload)
    if result is False:
        return Response(
            {
                "status": "rejected",
                "detail": "Limite de execuções mensais do plano foi atingido.",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    exec_log = result
    logger.info(
        "Webhook externo aceite: workflow_id=%s trigger_id=%s log_id=%s",
        workflow.id,
        trigger.id,
        exec_log.id,
    )
    return Response(
        {"status": "accepted", "log_id": exec_log.id},
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
