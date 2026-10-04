"""Tarefas assíncronas (Django Q) da app workflows."""
import json
import logging
import re
import time
import traceback

import requests
from core.queue import QueueUnavailable, enqueue
from django_q.tasks import async_task

from billing.decorators import check_quota_limit
from accounts.message_usage import record_automation_run, record_outbound_message_send
from accounts.models import OrganizationMembership
from extraction.ai_wrapper import check_and_update_quota
from integrations.evolution import WhatsAppEvolutionExecutor
from integrations.models import AppConnection
from integrations.webhook_executor import WebhookExecutor
from audit import service as audit_service
from cadrius.sentry_context import set_sentry_context
from notifications.services import (
    ACTION_LABELS,
    notify_automation_failed,
    notify_automation_succeeded,
    notify_integration_failure,
)
from workflows.models import Action, ExecutionLog, Workflow

logger = logging.getLogger(__name__)

# Tentativas para chamadas HTTP externas (webhook / Evolution) antes de gravar FAILED no log.
_WORKFLOW_EXTERNAL_MAX_ATTEMPTS = 3
# Pausa em segundos entre tentativas (após 1.ª e 2.ª falha).
_WORKFLOW_RETRY_BACKOFF_SEC = (1.0, 2.0)

# Limite para error_message (TextField); traceback completo pode ser enorme.
_MAX_ERROR_MESSAGE_LEN = 8000


def _failure_log_message(prefix: str, exc: BaseException) -> str:
    """Mensagem para o campo error_message: prefixo + traceback resumido (truncado)."""
    tb = traceback.format_exc()
    body = f"{prefix}\n\n{type(exc).__name__}: {exc}\n\n--- Traceback ---\n{tb}"
    if len(body) > _MAX_ERROR_MESSAGE_LEN:
        return body[: _MAX_ERROR_MESSAGE_LEN - 30] + "\n...[mensagem truncada]"
    return body


# Marcadores {{ ... }} ainda presentes após o render = chave não existiu no gatilho.
_TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.DOTALL)


def _list_unresolved_template_vars(rendered: str) -> list[str]:
    """Nomes (ou caminhos a.b) de variáveis que continuam por substituir no texto rendido."""
    if not rendered:
        return []
    found = []
    for m in _TEMPLATE_VAR_PATTERN.finditer(rendered):
        inner = (m.group(1) or "").strip()
        if inner:
            found.append(inner)
    return found


def render_action_payload(template_str, trigger_data):
    """
    Monta o corpo da ação: substitui marcadores {{chave}} (e {{obj.campo}}) pelos valores
    em trigger_data (JSON do webhook, e-mail processado, etc.). Se a chave não existir,
    mantém o marcador original.
    """
    if not template_str:
        return ""

    data = trigger_data if trigger_data is not None else {}

    def replacer(match):
        keys = match.group(1).strip().split(".")
        value = data
        try:
            for key in keys:
                value = value[key]
            # Escapa para o contexto de string JSON do template: sem isto um valor vindo de um
            # webhook público como `x","number":"5511..."` injetava/sobrescrevia campos da ação
            # (ex.: redirecionar mensagens de WhatsApp para outro número).
            return json.dumps(str(value), ensure_ascii=False)[1:-1]
        except (KeyError, TypeError):
            return match.group(0)

    return re.sub(r"\{\{(.*?)\}\}", replacer, template_str)


def extract_trigger_payload(exec_log: ExecutionLog) -> dict:
    """
    Lê o JSON guardado em trigger_payload no momento do disparo e devolve um dicionário
    para substituição no template. None vazio; string tenta json.loads; outros tipos
    ficam em {"_value": ...} para não quebrar o fluxo.
    """
    raw = exec_log.trigger_payload
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}
    return {"_value": raw}


def parse_action_template_to_dict(template_str: str, trigger_data: dict) -> dict:
    """
    Renderiza o template e faz parse seguro com json.loads (sem eval nem pickle).
    Garante que o resultado final é um dicionário Python (objeto JSON na raiz).

    Levanta ValueError de forma explícita se faltarem variáveis no gatilho (marcadores
    {{...}} por substituir) ou se o JSON final for inválido.
    """
    try:
        rendered = render_action_payload(template_str, trigger_data)
        stripped = (rendered or "").strip()
        if not stripped:
            return dict(trigger_data) if isinstance(trigger_data, dict) else {}

        missing = _list_unresolved_template_vars(rendered)
        if missing:
            raise ValueError(
                "O template da ação exige campos que não vieram no gatilho (ou estão mal "
                "escritos no template): "
                + ", ".join(missing)
            )

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "O texto após substituir as variáveis não é JSON válido. "
                "Confirme o payload_template e os dados do gatilho."
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                "O JSON da ação tem de ser um objeto na raiz (ex.: {\"number\": \"...\"}), "
                "não uma lista nem um valor simples entre aspas."
            )
        return parsed

    except ValueError:
        raise
    except Exception as exc:
        logger.exception("Falha ao interpretar template da ação")
        raise ValueError(
            "Erro inesperado ao montar o payload da ação a partir do template e do gatilho."
        ) from exc


def _connection_belongs_to_organization(
    connection: AppConnection | None, organization
) -> bool:
    """
    CAD-062: a AppConnection só é válida se estiver ativa e o proprietário for
    membro ativo do mesmo escritório do workflow.
    """
    if connection is None or organization is None:
        return False
    if not connection.is_active:
        return False
    return OrganizationMembership.objects.filter(
        user_id=connection.user_id,
        organization_id=organization.pk,
        is_active=True,
    ).exists()


def _resolve_action_connection(workflow: Workflow, tenant) -> AppConnection | None:
    """
    Obtém a AppConnection do gatilho e valida isolamento por organização.
    (Action ainda não tem FK ``connection`` — a ligação operacional é no Trigger.)
    """
    trigger = getattr(workflow, "trigger", None)
    if trigger is None or not trigger.connection_id:
        return None

    connection = trigger.connection
    if not _connection_belongs_to_organization(connection, tenant):
        raise ValueError(
            "A AppConnection do gatilho não pertence à organização deste workflow "
            "(credenciais de outro escritório ou utilizador sem membership ativa)."
        )
    return connection


def _evolution_credentials_from_connection(connection: AppConnection, tenant) -> tuple[str | None, str | None, str]:
    """Extrai base_url / api_key / instance_name das credentials da conexão WHATSAPP."""
    creds = connection.credentials if isinstance(connection.credentials, dict) else {}
    base_url = creds.get("base_url") or creds.get("baseUrl")
    api_key = (
        creds.get("api_key")
        or creds.get("apikey")
        or creds.get("token")
        or creds.get("global_key")
    )
    instance_name = (
        creds.get("instance_name")
        or creds.get("instance")
        or f"instancia_org_{tenant.pk}"
    )
    return base_url, api_key, str(instance_name)


def _dispatch_action_execution(
    action: Action,
    workflow: Workflow,
    final_data: dict,
    *,
    tenant,
    connection: AppConnection | None,
) -> dict:
    """
    Roteador por action_type: instancia o executor certo e devolve o conteúdo para final_result.
    Credenciais de integração são cruzadas com a organização do fluxo (CAD-062).
    """
    at = (action.action_type or "").strip()

    match at:
        case "WHATSAPP_EVOLUTION":
            if connection is None:
                raise ValueError(
                    "Ação WHATSAPP_EVOLUTION exige AppConnection no gatilho do workflow."
                )
            if (connection.app_name or "").upper() != "WHATSAPP":
                raise ValueError(
                    "A AppConnection do gatilho não é do tipo WHATSAPP; "
                    "credenciais Evolution recusadas por isolamento de organização."
                )
            base_url, api_key, instance_name = _evolution_credentials_from_connection(
                connection, tenant
            )
            executor = WhatsAppEvolutionExecutor(base_url=base_url, api_key=api_key)
            resp_data = executor.send(instance_name, final_data)
            return resp_data if isinstance(resp_data, dict) else {"response": resp_data}

        case "WEBHOOK" | "":
            # Webhook de saída usa endpoint da Action; se houver connection WEBHOOK no
            # gatilho, já foi validada como pertencente ao tenant em _resolve_action_connection.
            executor = WebhookExecutor(action)
            response = executor.execute(final_data)
            response.raise_for_status()
            return {
                "status_code": response.status_code,
                "body": (response.text or "")[:10000],
            }

        case "EMAIL_SMTP":
            raise ValueError("Tipo de ação EMAIL_SMTP ainda não implementado no runner.")

        case _:
            raise ValueError(f"Tipo de Action '{action.action_type}' não suportada.")


def _resolve_execution_user_id(exec_log: ExecutionLog, workflow: Workflow):
    """Utilizador dono da contagem: quem disparou ou proprietário da conexão do gatilho."""
    if exec_log.triggered_by_id:
        return exec_log.triggered_by_id

    trigger = getattr(workflow, "trigger", None)
    if trigger is not None and trigger.connection_id:
        return trigger.connection.user_id

    return None


def process_workflow_execution(execution_log_id):
    """
    Worker: lê o ExecutionLog, confirma que o workflow ainda está ativo, executa a ação
    e atualiza o registo (resultado, tempo, erros).
    Cronómetro com time.time(): diferença em segundos × 1000 → execution_time_ms.

    CAD-062: o contexto de organização é ``tenant = execution_log.workflow.organization``;
    quota de IA e credenciais de integração usam estritamente esse tenant.
    """
    t0 = time.time()

    def elapsed_ms() -> int:
        return int((time.time() - t0) * 1000)

    try:
        exec_log = ExecutionLog.objects.select_related(
            "workflow__organization__plan",
            "workflow__trigger__connection__user",
            "triggered_by",
        ).get(id=execution_log_id)
    except ExecutionLog.DoesNotExist:
        logger.error("execution_log_id=%s ExecutionLog não encontrado.", execution_log_id)
        return

    workflow = exec_log.workflow
    # CAD-062: isolamento de contexto — organização do fluxo em execução.
    tenant = exec_log.workflow.organization
    # Worker em background: o Sentry deve indicar o escritório afetado (CAD-056).
    set_sentry_context(exec_log.triggered_by, workflow.organization)
    trigger_data = extract_trigger_payload(exec_log)

    if tenant is None:
        exec_log.status = "FAILED"
        exec_log.error_message = "Workflow sem organização associada; execução cancelada."
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "error_message", "execution_time_ms"]
        )
        return

    if not getattr(tenant, "is_active", True):
        exec_log.status = "FAILED"
        exec_log.error_message = "Organização inativa; execução cancelada."
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "error_message", "execution_time_ms"]
        )
        return

    if not workflow.is_active:
        exec_log.status = "FAILED"
        exec_log.error_message = "Workflow inativo; execução cancelada."
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "error_message", "execution_time_ms"]
        )
        logger.warning(
            "execution_log_id=%s workflow_id=%s não está ativo (is_active=False); execução cancelada.",
            execution_log_id,
            workflow.id,
        )
        return

    # Governança de IA: ação externa disparada por conteúdo extraído por IA aguarda confirmação humana
    # (a quota só é consumida quando a execução realmente acontece).
    if exec_log.ai_origin and exec_log.review_decision != "approved":
        from aigov.guard import get_policy

        if get_policy(tenant).requires_execution_review():
            exec_log.status = "PENDING_REVIEW"
            exec_log.save(update_fields=["status"])
            audit_service.log(
                "ai.blocked", actor_type="system", organization=tenant, target=exec_log, outcome="denied",
                reason="execução de origem IA aguarda confirmação humana",
            )
            logger.info("execution_log_id=%s aguarda revisão humana (origem IA)", execution_log_id)
            return

    action = None  # definido dentro do try; usado também nos handlers de erro
    try:
        # CAD-062: quota sempre no tenant do workflow (nunca outro escritório).
        ok, quota_message = check_and_update_quota(tenant)
        if not ok:
            exec_log.status = "FAILED"
            exec_log.error_message = quota_message or (
                "Limite de extrações/IA do plano do escritório foi atingido."
            )
            exec_log.execution_time_ms = elapsed_ms()
            exec_log.save(
                update_fields=["status", "error_message", "execution_time_ms"]
            )
            return

        action = workflow.actions.order_by("id").first()
        if not action:
            raise ValueError("Workflow sem ações configuradas.")

        connection = _resolve_action_connection(workflow, tenant)

        final_data = parse_action_template_to_dict(action.payload_template, trigger_data)

        for attempt in range(1, _WORKFLOW_EXTERNAL_MAX_ATTEMPTS + 1):
            try:
                exec_log.final_result = _dispatch_action_execution(
                    action,
                    workflow,
                    final_data,
                    tenant=tenant,
                    connection=connection,
                )
                break
            except requests.exceptions.RequestException as exc:
                if attempt >= _WORKFLOW_EXTERNAL_MAX_ATTEMPTS:
                    raise
                wait_s = _WORKFLOW_RETRY_BACKOFF_SEC[
                    min(attempt - 1, len(_WORKFLOW_RETRY_BACKOFF_SEC) - 1)
                ]
                logger.warning(
                    "execution_log_id=%s tentativa %s/%s falhou (%s). "
                    "Nova tentativa em %.1fs.",
                    execution_log_id,
                    attempt,
                    _WORKFLOW_EXTERNAL_MAX_ATTEMPTS,
                    exc,
                    wait_s,
                )
                time.sleep(wait_s)

        logger.info(
            "execution_log_id=%s workflow_id=%s concluído com sucesso em %sms",
            execution_log_id,
            workflow.id,
            elapsed_ms(),
        )
        exec_log.status = "SUCCESS"
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "final_result", "execution_time_ms"]
        )

        user_id = _resolve_execution_user_id(exec_log, workflow)
        record_automation_run(user_id)
        record_outbound_message_send(user_id, action.action_type)
        _audit_outbound(exec_log, tenant, action.action_type, "success")
        notify_automation_succeeded(exec_log, action.action_type, user_id, trigger_data)

    except requests.exceptions.RequestException as e:
        _audit_outbound(exec_log, tenant, getattr(action, "action_type", ""), "error")
        logger.error(
            "execution_log_id=%s workflow_id=%s envio falhou após %s tentativas: %s: %s",
            execution_log_id,
            workflow.id,
            _WORKFLOW_EXTERNAL_MAX_ATTEMPTS,
            type(e).__name__,
            e,
            exc_info=True,
        )
        exec_log.status = "FAILED"
        exec_log.error_message = _failure_log_message(
            f"Erro na requisição HTTP externa após {_WORKFLOW_EXTERNAL_MAX_ATTEMPTS} tentativas "
            "(ex.: API indisponível ou resposta inválida).",
            e,
        )
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "error_message", "execution_time_ms"]
        )
        notify_integration_failure(
            integration=ACTION_LABELS.get(action.action_type, action.action_type),
            actor_id=_resolve_execution_user_id(exec_log, workflow),
            organization=workflow.organization,
            detalhes=str(e),
            dedupe_key=f"automacao-erro:{exec_log.pk}",
        )

    except Exception as e:
        logger.exception(
            "execution_log_id=%s workflow_id=%s erro interno no process_workflow_execution",
            execution_log_id,
            workflow.id,
        )
        exec_log.status = "FAILED"
        exec_log.error_message = _failure_log_message(
            "Erro interno ao processar a execução do workflow.",
            e,
        )
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "error_message", "execution_time_ms"]
        )
        notify_automation_failed(exec_log, _resolve_execution_user_id(exec_log, workflow))


_MESSAGE_ACTIONS = {"WHATSAPP_EVOLUTION", "EMAIL_SMTP"}


def _audit_outbound(exec_log, tenant, action_type, outcome):
    """
    RNE-011: toda comunicação/chamada externa gerada pelo sistema deixa um registro IMUTÁVEL com o
    estado de entrega. Só metadados (tipo de ação, resultado, IDs) — nunca destinatário nem conteúdo.
    """
    audit_service.log(
        "message.sent" if action_type in _MESSAGE_ACTIONS else "integration.call",
        actor_type="system", organization=tenant, target=exec_log,
        outcome="success" if outcome == "success" else "error",
        changes={"action_type": action_type, "execution_log_id": exec_log.pk, "ai_origin": exec_log.ai_origin},
        data_categories=["contato", "conteudo_comunicacao"], legal_basis="contrato",
    )


@check_quota_limit
def execute_workflow_pipeline(workflow_id, payload, user_id=None, ai_origin=False):
    """
    Ponto de entrada (quota + registo): cria ExecutionLog e enfileira o processamento pesado.
    ``user_id``: utilizador logado ou proprietário da conexão que originou o disparo.
    """
    workflow = Workflow.objects.get(id=workflow_id)
    exec_log = ExecutionLog.objects.create(
        workflow=workflow,
        status="PENDING",
        trigger_payload=payload,
        triggered_by_id=user_id,
        ai_origin=ai_origin,
    )
    # Runner (CAD-001): fila pesada com o ID do log recém-criado.
    try:
        enqueue("workflows.tasks.process_workflow_execution", exec_log.id)
    except QueueUnavailable:
        # Broker fora do ar: não deixa a execução "PENDING" para sempre; quem chamou recebe 503 e tenta de novo.
        exec_log.status = "FAILED"
        exec_log.error_message = "Fila de processamento indisponível; execução não iniciada."
        exec_log.save(update_fields=["status", "error_message"])
        raise
    return exec_log
