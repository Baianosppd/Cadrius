"""
Serviços de domínio da app workflows (orquestração, integração com extração, etc.).
"""
import os

from django.conf import settings

from accounts.models import Organization

from extraction.ai_wrapper import check_and_update_quota, extract_fields_from_text

from .exceptions import WorkflowGenerationQuotaExceeded
from .prompts import CADRIUS_DOMAIN_CONTEXT_TEMPLATE
from .schemas import WorkflowGenerationSchema

__all__ = [
    "extract_fields_from_text",
    "CADRIUS_DOMAIN_CONTEXT_TEMPLATE",
    "generate_workflow_from_prompt",
    "WorkflowGenerationQuotaExceeded",
]


def _workflow_ai_provider() -> str:
    """
    Provedor para geração de workflow: prioriza o mais rápido entre os configurados (Groq),
    depois Gemini, depois OpenAI. Sobrescreve com ``WORKFLOW_AI_PROVIDER`` em settings se definido.
    """
    explicit = getattr(settings, "WORKFLOW_AI_PROVIDER", None)
    if explicit in ("GROQ", "GEMINI", "OPENAI"):
        return explicit
    if os.environ.get("GROQ_API_KEY"):
        return "GROQ"
    if os.environ.get("GEMINI_API_KEY"):
        return "GEMINI"
    if os.environ.get("OPENAI_API_KEY"):
        return "OPENAI"
    return "GROQ"


def generate_workflow_from_prompt(user_prompt: str, organization: Organization) -> dict | None:
    """
    Chama a IA para gerar um objeto compatível com ``WorkflowGenerationSchema`` a partir
    de linguagem natural. Usa ``extract_fields_from_text`` (validação Pydantic) e o
    provedor definido em ``_workflow_ai_provider()`` (Groq/Gemini/OpenAI conforme chaves).

    Antes de qualquer chamada ao LLM, usa ``check_and_update_quota(organization)`` para
    respeitar o limite mensal de extrações/IA do plano do escritório.
    """
    ok, quota_message = check_and_update_quota(organization)
    if not ok:
        raise WorkflowGenerationQuotaExceeded(quota_message)

    prompt_template = (
        f"{CADRIUS_DOMAIN_CONTEXT_TEMPLATE}\n\n"
        "## Objetivo\n"
        "Leia o TEXTO DE ENTRADA (pedido do utilizador em linguagem natural) e devolva "
        "**apenas** dados que possam ser serializados no schema WorkflowGenerationSchema: "
        "`workflow_name`, `workflow_description`, `trigger` (event_type, payload_mapping) "
        "e `actions` (lista de ações com action_type, endpoint_url quando for WEBHOOK, "
        "payload_template com templates JSON e marcadores {{variável}} quando fizer sentido).\n"
    )
    return extract_fields_from_text(
        text=user_prompt.strip(),
        schema=WorkflowGenerationSchema,
        prompt_template=prompt_template,
        provider=_workflow_ai_provider(),
    )
