"""Contadores de uso por utilizador (dashboard)."""
from django.db.models import F

from accounts.models import UserMessageSendCount


def _increment_field(user_id, field: str) -> None:
    if not user_id:
        return
    UserMessageSendCount.objects.get_or_create(user_id=user_id)
    UserMessageSendCount.objects.filter(user_id=user_id).update(
        **{field: F(field) + 1}
    )


def record_outbound_message_send(user_id, action_type: str) -> None:
    """Incrementa +1 após envio bem-sucedido de WhatsApp ou e-mail."""
    at = (action_type or "").strip()
    if at == "WHATSAPP_EVOLUTION":
        _increment_field(user_id, "whatsapp_count")
    elif at == "EMAIL_SMTP":
        _increment_field(user_id, "email_count")


def record_automation_run(user_id) -> None:
    """Incrementa +1 após execução bem-sucedida de uma automação."""
    _increment_field(user_id, "automations_run_count")


def record_document_analysis(user_id) -> None:
    """Incrementa +1 após análise de documento/conteúdo com IA (ex.: e-mail processado)."""
    _increment_field(user_id, "document_analysis_count")


def dashboard_stats_for_user(user) -> dict:
    """Cartões do painel, contados nos dados reais do escritório (CAD-230).

    Antes vinham só dos contadores por pessoa (``UserMessageSendCount``), que o fluxo novo (documentos enviados, Regras,
    mensagens das automações) não incrementava: o painel ficava parado. Os contadores antigos ainda valem como piso.
    """
    empty = {"total_documentos": 0, "automacoes_rodadas": 0, "mensagens_enviadas": 0, "automacoes_ativas": 0,
             "tarefas_hoje": 0, "tarefas_atrasadas": 0}
    if user is None or not getattr(user, "is_authenticated", False):
        return empty

    from django.utils import timezone

    from accounts.team_roles import get_active_membership
    from tasks.models import UserTask

    counts, _ = UserMessageSendCount.objects.get_or_create(user=user)
    today = timezone.localdate()
    pending = UserTask.objects.filter(responsavel=user, completed=False)
    out = {**empty,
           "total_documentos": counts.document_analysis_count,
           "automacoes_rodadas": counts.automations_run_count,
           "mensagens_enviadas": counts.messages_sent_total,
           "tarefas_hoje": UserTask.objects.filter(responsavel=user, scheduled_at__date=today).count(),
           "tarefas_atrasadas": pending.filter(scheduled_at__date__lt=today).count()}
    membership = get_active_membership(user)
    if membership is None:
        return out
    org = membership.organization

    from audit.models import AuditEvent
    from automations.models import Rule, RuleRun
    from documents.models import Document
    from workflows.models import ExecutionLog, Workflow

    runs = RuleRun.objects.filter(organization=org, status=RuleRun.Status.SUCCESS).count()
    runs += ExecutionLog.objects.filter(workflow__organization=org).count()
    sent = AuditEvent.objects.filter(organization_id=org.pk, action="message.sent", outcome="success").count()
    out.update({
        "total_documentos": max(Document.objects.filter(organization=org).count(), out["total_documentos"]),
        "automacoes_rodadas": max(runs, out["automacoes_rodadas"]),
        "mensagens_enviadas": max(sent, out["mensagens_enviadas"]),
        "automacoes_ativas": Rule.objects.filter(organization=org, enabled=True).count()
        + Workflow.objects.filter(organization=org, is_active=True).count(),
    })
    return out
