"""Agregações simples para a página de Automações."""
from django.db.models import Sum

from .models import ExecutionLog, Workflow


def automation_stats_for_organization(organization) -> dict:
    """
    Contagens por escritório (tenant):
    - automacoes_ativas: workflows com is_active=True
    - total_execucoes: registos em ExecutionLog (cada disparo do fluxo)
    - tempo_economizado: soma de execution_time_ms convertida em horas (inteiro)
    """
    if organization is None:
        return {
            "automacoes_ativas": 0,
            "total_execucoes": 0,
            "tempo_economizado": 0,
        }

    automacoes_ativas = Workflow.objects.filter(
        organization=organization,
        is_active=True,
    ).count()

    logs = ExecutionLog.objects.filter(workflow__organization=organization)
    total_execucoes = logs.count()

    total_ms = logs.filter(execution_time_ms__isnull=False).aggregate(
        total=Sum("execution_time_ms")
    )["total"] or 0
    tempo_economizado = int(total_ms // (1000 * 60 * 60))

    return {
        "automacoes_ativas": automacoes_ativas,
        "total_execucoes": total_execucoes,
        "tempo_economizado": tempo_economizado,
    }
