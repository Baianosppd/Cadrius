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
    """Três cards do dashboard para o utilizador autenticado."""
    if user is None or not getattr(user, "is_authenticated", False):
        return {
            "total_documentos": 0,
            "automacoes_rodadas": 0,
            "mensagens_enviadas": 0,
        }

    counts, _ = UserMessageSendCount.objects.get_or_create(user=user)
    return {
        "total_documentos": counts.document_analysis_count,
        "automacoes_rodadas": counts.automations_run_count,
        "mensagens_enviadas": counts.messages_sent_total,
    }
