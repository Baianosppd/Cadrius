"""Criação e leitura de notificações (sino)."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.utils import timezone

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership

from .models import Notification

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
PRAZO_WINDOW_DAYS = 5
PRAZO_LOOKBACK_DAYS = 365

DOCUMENTOS_LINK = "/documentos"
AUTOMACOES_LINK = "/automacoes"


def _recipient_ids(organization, actor_id):
    """Quem originou o evento + owner/admin do escritório."""
    from accounts.models import OrganizationMembership

    ids = set()
    if actor_id:
        ids.add(actor_id)
    if organization is not None:
        ids.update(
            OrganizationMembership.objects.filter(
                organization=organization,
                is_active=True,
                role__in=MANAGE_TEAM_ROLES,
            ).values_list("user_id", flat=True)
        )
    return ids


def notify(
    *,
    type,
    title,
    description="",
    actor_id=None,
    organization=None,
    origem="",
    documento="",
    acao="",
    detalhes="",
    action_label="",
    link="",
    dedupe_key="",
):
    """
    Cria a notificação para o autor do evento e para owner/admin do escritório.
    Nunca levanta exceção: falha de notificação não pode derrubar o fluxo principal.
    """
    try:
        if organization is None and actor_id:
            from accounts.models import CustomUser

            actor = CustomUser.objects.filter(pk=actor_id).first()
            membership = get_active_membership(actor) if actor else None
            organization = membership.organization if membership else None

        recipients = _recipient_ids(organization, actor_id)
        if not recipients:
            return 0

        Notification.objects.bulk_create(
            [
                Notification(
                    user_id=user_id,
                    organization=organization,
                    type=type,
                    title=title,
                    description=description,
                    origem=origem,
                    documento=documento,
                    acao=acao,
                    detalhes=detalhes,
                    action_label=action_label,
                    link=link,
                    dedupe_key=dedupe_key,
                )
                for user_id in recipients
            ],
            ignore_conflicts=True,
        )
        return len(recipients)
    except Exception:
        logger.exception("Falha ao criar notificação '%s'", title)
        return 0


# --- Eventos ---------------------------------------------------------------


def notify_document_uploaded(document):
    return notify(
        type=Notification.Type.DOCUMENTO,
        title="Novo documento carregado",
        description=f"{document.nome} foi enviado com sucesso.",
        actor_id=document.uploaded_by_id,
        organization=document.organization,
        origem="Módulo de Documentos",
        documento=document.nome,
        acao="Upload concluído",
        detalhes="O documento está disponível na listagem de documentos.",
        action_label="Ir para Módulo de Documentos",
        link=DOCUMENTOS_LINK,
        dedupe_key=f"documento-upload:{document.pk}",
    )


def notify_document_analyzed(email_message, organization, extracted):
    subject = (email_message.subject or "Documento").strip()
    has_prazo = isinstance(extracted, dict) and bool(extracted.get("prazo_fatal"))
    description = (
        f"{subject} foi processado e os prazos foram extraídos."
        if has_prazo
        else f"{subject} foi processado com sucesso."
    )
    return notify(
        type=Notification.Type.DOCUMENTO,
        title="Documento analisado com sucesso",
        description=description,
        actor_id=email_message.mailbox.user_id,
        organization=organization,
        origem="Módulo de Documentos",
        documento=subject,
        acao="Análise concluída com sucesso",
        detalhes="O conteúdo foi analisado pela IA e encaminhado para automação.",
        action_label="Ir para Módulo de Documentos",
        link=DOCUMENTOS_LINK,
        dedupe_key=f"documento-analise:{email_message.pk}",
    )


ACTION_LABELS = {
    "WHATSAPP_EVOLUTION": "WhatsApp",
    "WEBHOOK": "Webhook",
    "EMAIL_SMTP": "E-mail",
}


def _client_name(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("customer_name", "nome_cliente", "cliente"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    return None


def notify_automation_succeeded(exec_log, action_type, actor_id, trigger_data=None):
    workflow = exec_log.workflow
    cliente = _client_name(trigger_data)
    if action_type == "WHATSAPP_EVOLUTION":
        description = "WhatsApp enviado automaticamente"
    else:
        description = f"{workflow.name} executada automaticamente"
    description = f"{description} para o cliente {cliente}." if cliente else f"{description}."
    return notify(
        type=Notification.Type.AUTOMACAO,
        title="Nova automação concluída",
        description=description,
        actor_id=actor_id,
        organization=workflow.organization,
        origem="Módulo de Automações",
        documento=workflow.name,
        acao="Execução concluída",
        detalhes="A automação foi concluída sem erros.",
        action_label="Ir para Automações",
        link=AUTOMACOES_LINK,
        dedupe_key=f"automacao-sucesso:{exec_log.pk}",
    )


def notify_integration_failure(*, integration, actor_id, organization=None, detalhes="", dedupe_key=""):
    return notify(
        type=Notification.Type.ERRO,
        title="Falha na sincronização",
        description=f"Não foi possível sincronizar com {integration}. Tente reconectar.",
        actor_id=actor_id,
        organization=organization,
        origem="Integrações",
        documento=integration,
        acao="Sincronização interrompida",
        detalhes=_truncate(detalhes),
        action_label="Ver integrações",
        link=AUTOMACOES_LINK,
        dedupe_key=dedupe_key,
    )


def notify_automation_failed(exec_log, actor_id):
    workflow = exec_log.workflow
    return notify(
        type=Notification.Type.ERRO,
        title="Erro na automação",
        description=f"{workflow.name} falhou durante a execução.",
        actor_id=actor_id,
        organization=workflow.organization,
        origem="Módulo de Automações",
        documento=workflow.name,
        acao="Execução interrompida",
        detalhes=_truncate(exec_log.error_message or "Erro desconhecido."),
        action_label="Ir para Automações",
        link=AUTOMACOES_LINK,
        dedupe_key=f"automacao-erro:{exec_log.pk}",
    )


def _truncate(text, limit=120):
    text = (text or "").strip()
    return f"{text[: limit - 3]}..." if len(text) > limit else text


# --- Prazos (gerados sob demanda, sem job) ----------------------------------


def _parse_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def _prazo_description(processo, dias):
    alvo = f"Prazo do processo {processo}" if processo else "Prazo"
    if dias == 0:
        return f"{alvo} vence hoje."
    if dias == 1:
        return f"{alvo} vence amanhã."
    return f"{alvo} vence em {dias} dias."


def sync_deadline_notifications(user):
    """
    Cria avisos de prazo (5 dias, 1 dia, no dia) para o utilizador a partir do
    ``prazo_fatal`` extraído nas execuções. Roda quando o front consulta o sino.
    """
    from workflows.models import ExecutionLog

    membership = get_active_membership(user)
    if membership is None:
        return 0

    is_manager = membership.role in MANAGE_TEAM_ROLES
    hoje = timezone.localdate()
    logs = ExecutionLog.objects.filter(
        workflow__organization=membership.organization,
        status="SUCCESS",
        trigger_payload__has_key="prazo_fatal",
        created_at__gte=timezone.now() - timedelta(days=PRAZO_LOOKBACK_DAYS),
    ).only("id", "trigger_payload", "triggered_by_id")
    if not is_manager:
        logs = logs.filter(triggered_by=user)

    novas = []
    for log in logs:
        payload = log.trigger_payload or {}
        prazo = _parse_date(payload.get("prazo_fatal"))
        if prazo is None:
            continue
        dias = (prazo - hoje).days
        if dias < 0 or dias > PRAZO_WINDOW_DAYS:
            continue
        marco = 0 if dias == 0 else 1 if dias == 1 else PRAZO_WINDOW_DAYS
        processo = str(payload.get("numero_processo") or "").strip()
        referencia = processo or f"execucao-{log.pk}"
        novas.append(
            Notification(
                user=user,
                organization=membership.organization,
                type=Notification.Type.PRAZO,
                title="Prazo próximo identificado",
                description=_prazo_description(processo, dias),
                origem="Módulo de Automações",
                documento=processo,
                acao="Prazo se aproximando",
                detalhes=f"Prazo fatal em {prazo.strftime('%d/%m/%Y')}.",
                action_label="Ver prazos",
                link=DOCUMENTOS_LINK,
                dedupe_key=f"prazo:{referencia}:{prazo.isoformat()}:{marco}",
            )
        )

    if novas:
        Notification.objects.bulk_create(novas, ignore_conflicts=True)
    return len(novas)


# --- Leitura -----------------------------------------------------------------


def purge_old_notifications(user):
    limite = timezone.now() - timedelta(days=RETENTION_DAYS)
    Notification.objects.filter(user=user, created_at__lt=limite).delete()


def refresh_user_notifications(user):
    """Chamado nas rotas de leitura: gera prazos pendentes e aplica retenção."""
    try:
        sync_deadline_notifications(user)
        purge_old_notifications(user)
    except Exception:
        logger.exception("Falha ao atualizar notificações do utilizador %s", user.pk)
