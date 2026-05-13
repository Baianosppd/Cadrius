"""Tarefas assíncronas (Django Q) da app workflows."""
import json
import logging
import re
import time

import requests
from django_q.tasks import async_task

from billing.decorators import check_quota_limit
from integrations.evolution import send_whatsapp_message
from workflows.models import Action, ExecutionLog, Workflow

logger = logging.getLogger(__name__)


def parse_dynamic_variables(template_str, payload):
    """
    Procura por padrões {{chave}} no template e substitui pelo valor do JSON original.
    Suporta aninhamento. Ex: {{cliente.nome}}
    """
    if not template_str:
        return ""

    def replacer(match):
        keys = match.group(1).strip().split(".")
        value = payload
        try:
            for key in keys:
                value = value[key]
            return str(value)
        except (KeyError, TypeError):
            return match.group(0)

    return re.sub(r"\{\{(.*?)\}\}", replacer, template_str)


def _action_headers(action: Action) -> dict:
    if not action.headers:
        return {}
    if isinstance(action.headers, dict):
        return dict(action.headers)
    return json.loads(action.headers)


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
    payload = exec_log.trigger_payload if exec_log.trigger_payload is not None else {}

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

        final_payload_str = parse_dynamic_variables(action.payload_template, payload)

        try:
            final_data = json.loads(final_payload_str) if final_payload_str else payload
        except json.JSONDecodeError:
            final_data = final_payload_str

        if action.action_type == "WHATSAPP_EVOLUTION":
            if isinstance(final_data, dict) and "number" in final_data and "text" in final_data:
                instance_name = f"instancia_org_{workflow.organization.id}"
                resp_data = send_whatsapp_message(
                    instance_name=instance_name,
                    number=final_data["number"],
                    message_text=final_data["text"],
                )
                exec_log.final_result = (
                    resp_data if isinstance(resp_data, dict) else {"response": resp_data}
                )
            else:
                raise ValueError(
                    "Payload template para WhatsApp inválido. O JSON deve conter 'number' e 'text'."
                )

        elif action.action_type in ("WEBHOOK", ""):
            response = requests.request(
                method=action.method.upper() if action.method else "POST",
                url=action.endpoint_url,
                json=final_data if isinstance(final_data, dict) else None,
                data=final_data if not isinstance(final_data, dict) else None,
                headers=_action_headers(action),
                timeout=15,
            )
            response.raise_for_status()
            exec_log.final_result = {
                "status_code": response.status_code,
                "body": (response.text or "")[:10000],
            }

        elif action.action_type == "EMAIL_SMTP":
            raise ValueError("Tipo de ação EMAIL_SMTP ainda não implementado no runner.")

        else:
            raise ValueError(f"Tipo de Action '{action.action_type}' não suportada.")

        exec_log.status = "SUCCESS"
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save()

    except requests.exceptions.RequestException as e:
        exec_log.status = "FAILED"
        exec_log.error_message = f"Erro na requisição externa: {str(e)}"
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save()

    except Exception as e:
        logger.exception("Erro no process_workflow_execution (log=%s)", execution_log_id)
        exec_log.status = "FAILED"
        exec_log.error_message = f"Erro interno do Cadrius: {str(e)}"
        exec_log.execution_time_ms = elapsed_ms()
        exec_log.save()


@check_quota_limit
def execute_workflow_pipeline(workflow_id, payload):
    """
    Ponto de entrada (quota + registo): cria ExecutionLog e enfileira o processamento pesado.
    """
    workflow = Workflow.objects.get(id=workflow_id)
    exec_log = ExecutionLog.objects.create(
        workflow=workflow,
        status="PENDING_REVIEW",
        trigger_payload=payload,
    )
    async_task("workflows.tasks.process_workflow_execution", exec_log.id)
