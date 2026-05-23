"""Tarefas assíncronas (Django Q) da app workflows."""
import json
import logging
import re
import time
import traceback

import requests
from django_q.tasks import async_task

from billing.decorators import check_quota_limit
from integrations.evolution import WhatsAppEvolutionExecutor
from integrations.webhook_executor import WebhookExecutor
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
            return str(value)
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


def _dispatch_action_execution(action: Action, workflow: Workflow, final_data: dict) -> dict:
    """
    Roteador por action_type: instancia o executor certo e devolve o conteúdo para final_result.
    """
    at = (action.action_type or "").strip()

    match at:
        case "WHATSAPP_EVOLUTION":
            instance_name = f"instancia_org_{workflow.organization.id}"
            executor = WhatsAppEvolutionExecutor()
            resp_data = executor.send(instance_name, final_data)
            return resp_data if isinstance(resp_data, dict) else {"response": resp_data}

        case "WEBHOOK" | "":
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


def process_workflow_execution(execution_log_id):
    """
    Worker: lê o ExecutionLog, confirma que o workflow ainda está ativo, executa a ação
    e atualiza o registo (resultado, tempo, erros).
    Cronómetro com time.time(): diferença em segundos × 1000 → execution_time_ms.
    """
    t0 = time.time()

    def elapsed_ms() -> int:
        return int((time.time() - t0) * 1000)

    try:
        exec_log = ExecutionLog.objects.select_related("workflow__organization").get(
            id=execution_log_id
        )
    except ExecutionLog.DoesNotExist:
        logger.error("ExecutionLog %s não encontrado.", execution_log_id)
        return

    workflow = exec_log.workflow
    trigger_data = extract_trigger_payload(exec_log)

    if not workflow.is_active:
        exec_log.status = "FAILED"
        exec_log.error_message = "Workflow inativo; execução cancelada."
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "error_message", "execution_time_ms"]
        )
        logger.warning(
            "ExecutionLog %s: workflow %s não está ativo (is_active=False).",
            execution_log_id,
            workflow.id,
        )
        return

    try:
        action = workflow.actions.order_by("id").first()
        if not action:
            raise ValueError("Workflow sem ações configuradas.")

        final_data = parse_action_template_to_dict(action.payload_template, trigger_data)

        for attempt in range(1, _WORKFLOW_EXTERNAL_MAX_ATTEMPTS + 1):
            try:
                exec_log.final_result = _dispatch_action_execution(
                    action, workflow, final_data
                )
                break
            except requests.exceptions.RequestException as exc:
                if attempt >= _WORKFLOW_EXTERNAL_MAX_ATTEMPTS:
                    raise
                wait_s = _WORKFLOW_RETRY_BACKOFF_SEC[
                    min(attempt - 1, len(_WORKFLOW_RETRY_BACKOFF_SEC) - 1)
                ]
                logger.warning(
                    "ExecutionLog %s: tentativa %s/%s falhou (%s). "
                    "Nova tentativa em %.1fs.",
                    execution_log_id,
                    attempt,
                    _WORKFLOW_EXTERNAL_MAX_ATTEMPTS,
                    exc,
                    wait_s,
                )
                time.sleep(wait_s)

        exec_log.status = "SUCCESS"
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "final_result", "execution_time_ms"]
        )

    except requests.exceptions.RequestException as e:
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

    except Exception as e:
        logger.exception("Erro no process_workflow_execution (log=%s)", execution_log_id)
        exec_log.status = "FAILED"
        exec_log.error_message = _failure_log_message(
            "Erro interno ao processar a execução do workflow.",
            e,
        )
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save(
            update_fields=["status", "error_message", "execution_time_ms"]
        )


@check_quota_limit
def execute_workflow_pipeline(workflow_id, payload):
    """
    Ponto de entrada (quota + registo): cria ExecutionLog e enfileira o processamento pesado.
    """
    workflow = Workflow.objects.get(id=workflow_id)
    exec_log = ExecutionLog.objects.create(
        workflow=workflow,
        status="PENDING",
        trigger_payload=payload,
    )
    # Runner (CAD-001): fila pesada com o ID do log recém-criado.
    async_task("workflows.tasks.process_workflow_execution", exec_log.id)
    return exec_log
