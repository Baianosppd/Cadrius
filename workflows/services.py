"""
Serviços de domínio da app workflows (orquestração, integração com extração, etc.).
"""

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


def _workflow_ai_provider(organization=None) -> str:
    """
    Provedor para geração de workflow: ``WORKFLOW_AI_PROVIDER`` em settings, se definido; senão o 1º provedor
    configurado (e permitido pelo escritório) na ordem da camada ``aigov.llm`` (CAD-221).
    """
    from aigov import llm

    explicit = getattr(settings, "WORKFLOW_AI_PROVIDER", None)
    if explicit in llm.PROVIDERS:
        return explicit
    allowed = None
    if organization is not None:
        from aigov.guard import get_policy
        allowed = get_policy(organization).allowed_providers
    found = llm.candidates(allowed, sensitive=True)
    return found[0] if found else "GROQ"


def generate_workflow_from_prompt(user_prompt: str, organization: Organization, user=None) -> dict | None:
    """
    Chama a IA para gerar um objeto compatível com ``WorkflowGenerationSchema`` a partir
    de linguagem natural. Usa ``extract_fields_from_text`` (validação Pydantic) e o
    provedor definido em ``_workflow_ai_provider()`` (Groq/Gemini/OpenAI conforme chaves).

    Antes de qualquer chamada ao LLM, usa ``check_and_update_quota(organization)`` para
    respeitar o limite mensal de extrações/IA do plano do escritório.
    """
    from aigov.guard import run_guarded

    user_id = getattr(user, 'id', None)
    ok, quota_message = check_and_update_quota(organization, user_id=user_id)
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
    provider = _workflow_ai_provider(organization)
    return run_guarded(
        organization=organization, user=user, kind='workflow_generation', provider=provider,
        categories=['processual'], input_text=user_prompt,
        fn=lambda: extract_fields_from_text(
            text=user_prompt.strip(), schema=WorkflowGenerationSchema,
            prompt_template=prompt_template, provider=provider,
        ),
    )
