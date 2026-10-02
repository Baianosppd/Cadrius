"""Histórico de sincronização: envios das automações para integrações externas."""
from __future__ import annotations

from django.db.models import OuterRef, Q, Subquery

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from core.activities import format_relative_time
from notifications.services import ACTION_LABELS
from workflows.models import Action, ExecutionLog

EXTERNAL_ACTION_TYPES = ("WHATSAPP_EVOLUTION", "WEBHOOK")
# prefixo gravado em workflows.tasks quando a chamada HTTP externa esgota as tentativas
EXTERNAL_FAILURE_PREFIX = "Erro na requisição HTTP externa"


def sync_history_queryset(user):
    membership = get_active_membership(user)
    if membership is None:
        return ExecutionLog.objects.none()

    first_action_type = Action.objects.filter(
        workflow=OuterRef("workflow"),
    ).order_by("id").values("action_type")[:1]

    qs = (
        ExecutionLog.objects.filter(workflow__organization=membership.organization)
        .annotate(integration_type=Subquery(first_action_type))
        .filter(integration_type__in=EXTERNAL_ACTION_TYPES)
        .filter(
            Q(status="SUCCESS")
            | Q(status="FAILED", error_message__startswith=EXTERNAL_FAILURE_PREFIX)
        )
        .select_related("workflow")
        .order_by("-created_at", "-id")
    )
    if membership.role not in MANAGE_TEAM_ROLES:
        qs = qs.filter(triggered_by=user)
    return qs


def sync_history_item(log) -> dict:
    integration = ACTION_LABELS.get(log.integration_type, log.integration_type)
    workflow_name = log.workflow.name
    if log.status == "SUCCESS":
        title = "Sincronização concluída"
        description = f"{workflow_name} enviado para {integration} com sucesso."
        status = "sucesso"
    else:
        title = "Falha na sincronização"
        description = f"Não foi possível enviar {workflow_name} para {integration}. Tente reconectar."
        status = "falha"
    return {
        "id": log.id,
        "title": title,
        "description": description,
        "time": format_relative_time(log.created_at),
        "status": status,
        "integration": integration,
        "created_at": log.created_at.isoformat(),
    }
