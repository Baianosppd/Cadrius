"""Agregações simples para a página de Automações."""
from django.db.models import Sum

from .models import ExecutionLog, Workflow

MINUTES_PER_STEP = 3


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

    # CAD-227: as Regras do escritório também são automações (antes o topo mostrava 0 com regra ligada).
    # Tempo economizado = estimativa de 3 minutos de trabalho manual por passo feito (não o tempo de máquina).
    from automations.models import Rule, RuleRun
    regras_ativas = Rule.objects.filter(organization=organization, enabled=True).count()
    runs = RuleRun.objects.filter(organization=organization).exclude(status=RuleRun.Status.SKIPPED)
    passos = sum(1 for r in runs.only("steps")[:5000] for st in (r.steps or []) if st.get("status") == "feito")
    minutos = (passos + total_execucoes) * MINUTES_PER_STEP

    return {
        "automacoes_ativas": automacoes_ativas + regras_ativas,
        "total_execucoes": total_execucoes + runs.count(),
        "tempo_economizado": tempo_economizado,
        "tempo_economizado_min": minutos,
    }
