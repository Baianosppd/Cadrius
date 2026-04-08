"""
Gateway genérico de webhooks: POST /api/webhooks/<identifier>/
"""

from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from workflows.models import Trigger

from .payload import WebhookPayloadError, parse_and_validate_webhook_json
from .queue_hook import enqueue_webhook_for_execution

logger = logging.getLogger(__name__)


def resolve_webhook_trigger(identifier: str) -> Trigger | None:
    """Localiza o trigger pela chave única `webhook_identifier`."""
    if not identifier or not str(identifier).strip():
        return None
    key = str(identifier).strip()
    return (
        Trigger.objects.select_related('workflow')
        .filter(webhook_identifier=key)
        .first()
    )


def build_execution_package(trigger: Trigger, payload: dict) -> dict:
    """Monta o dict entregue ao hook de fila (sem executar motor)."""
    wf = trigger.workflow
    return {
        'workflow_id': wf.id,
        'trigger_id': trigger.id,
        'payload': payload,
        'received_at': timezone.now().isoformat(),
    }


class WebhookGatewayView(APIView):
    """
    Aceita apenas POST com corpo JSON (objeto na raiz).
    identifier associa-se a Trigger.webhook_identifier.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, identifier):
        try:
            payload = parse_and_validate_webhook_json(request.body)
        except WebhookPayloadError as e:
            return Response(
                {'detail': e.message, 'code': e.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        trigger = resolve_webhook_trigger(identifier)
        if trigger is None:
            return Response(
                {'detail': 'Trigger não encontrado para este identifier.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        workflow = trigger.workflow
        if not workflow.is_active:
            return Response(
                {'detail': 'Workflow inativo.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prepared = build_execution_package(trigger, payload)
        enqueue_webhook_for_execution(prepared)

        logger.info(
            'Webhook aceito workflow_id=%s trigger_id=%s identifier=%s',
            workflow.id,
            trigger.id,
            identifier,
        )

        return Response(
            {
                'detail': 'Aceito.',
                'workflow_id': workflow.id,
                'trigger_id': trigger.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )
