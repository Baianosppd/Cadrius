# extraction/ai_wrapper.py
import json
import logging

from pydantic import BaseModel, ValidationError

# Importa os schemas definidos por Juliano
from aigov import llm
from aigov.sanitize import UNTRUSTED_NOTICE, wrap_untrusted

from .schemas import ServiceOrderSchema

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 2


def extract_fields_from_text(
    text: str, 
    schema: type[BaseModel], 
    prompt_template: str, 
    provider: str = 'OPENAI',
    examples: list = None,
    fallbacks: list | tuple = (),
) -> dict | None:
    """
    Roteador universal para extração de dados com validação Pydantic.
    ``fallbacks`` (CAD-224): se o provedor cair ou não devolver JSON válido, os próximos da cadeia da atividade assumem.
    """
    schema_json = schema.model_json_schema()
    
    # 1. Montagem do Prompt de Sistema
    system_prompt = (
        "Você é um extrator de dados altamente eficiente. Sua única tarefa é analisar o texto "
        "fornecido e retornar os dados estritamente no formato JSON, conforme o schema abaixo. "
        f"Se não for possível preencher um campo, use `null` ou um valor padrão razoável.\n\n"
        f"SCHEMA JSON: {json.dumps(schema_json)}\n\n{UNTRUSTED_NOTICE}"
    )

    # 2. Montagem da Mensagem do Usuário
    # Texto de terceiros é NÃO CONFIÁVEL: delimitado, sem caracteres de controle e com tamanho limitado.
    user_prompt = f"{prompt_template}\n\nTEXTO DE ENTRADA:\n{wrap_untrusted(text)}"
    
    base_prompt = user_prompt
    for current in [provider, *[f for f in fallbacks if f != provider]]:
        result = _try_provider(current, schema, system_prompt, base_prompt)
        if result is not None:
            return result
        logger.warning('Extração: %s não resolveu; tentando o próximo provedor da cadeia.', current)
    logger.error("Extração falhou em todos os provedores. Retornando None.")
    return None


def _try_provider(provider, schema, system_prompt, user_prompt):
    """Tentativas com correção de JSON num provedor; None se falhar."""
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            logger.info(f"Tentativa {attempt + 1}: Chamando API {provider}...")
            
            # ROTEADOR DE IA (CAD-221): todos os provedores passam pela camada única aigov.llm
            raw_json_output = _call(provider, system_prompt, user_prompt)

            # 3. VALIDAÇÃO PYDANTIC (CRÍTICO)
            validated_model = schema.model_validate_json(raw_json_output)
            return validated_model.model_dump(mode='json')

        except json.JSONDecodeError:
            logger.error(f"Tentativa {attempt + 1}: Resposta da IA ({provider}) não é um JSON válido.")
            user_prompt += "\nA saída anterior não foi um JSON válido. Por favor, corrija e retorne APENAS o JSON."
            
        except ValidationError as e:
            logger.error(f"Tentativa {attempt + 1}: Falha na validação Pydantic. Erro: {e}")
            error_message = f"O JSON retornado falhou na validação. Erros:\n{e}"
            user_prompt += f"\nCorrija os erros de schema no seu JSON:\n{error_message}"

        except Exception as e:
            logger.critical(f"Erro na comunicação com a API {provider}: {type(e).__name__}")
            break # Falha crítica de rede ou chave errada: passa ao próximo provedor

    return None

# --- FUNÇÕES INTERNAS DE CHAMADA ÀS APIS ---

def _call(provider, system_prompt, user_prompt):
    named = {'OPENAI': _call_openai, 'GROQ': _call_groq, 'GEMINI': _call_gemini}.get(provider)
    if named:
        return named(system_prompt, user_prompt)
    if provider not in llm.PROVIDERS:
        raise ValueError(f"Provedor de IA desconhecido: {provider}")
    return llm.complete_json(provider, system_prompt, user_prompt)


def _call_openai(system_prompt, user_prompt):
    return llm.complete_json('OPENAI', system_prompt, user_prompt)


def _call_groq(system_prompt, user_prompt):
    return llm.complete_json('GROQ', system_prompt, user_prompt)


def _call_gemini(system_prompt, user_prompt):
    return llm.complete_json('GEMINI', system_prompt, user_prompt)


# --- MOCK DE TESTE PARA CI/CD ---
def mock_extract_fields_from_text(text: str, schema: type[BaseModel], **kwargs) -> dict | None:
    logger.warning("Usando MOCK de extração de IA. Apenas para testes unitários.")
    if schema == ServiceOrderSchema:
        return ServiceOrderSchema(
            document_type='SERVICE_ORDER',
            confidence_score=95,
            customer_name="Cliente Mock Teste LTDA",
            service_description="Implementação do módulo de IA conforme specs.",
            priority='HIGH',
            target_sla_days=7,
            contact_phone="9999-8888"
        ).model_dump()
    return None

def check_and_update_quota(organization, user_id=None):
    """ Verifica e desconta 1 crédito do plano do escritório e da cota do membro (se houver). """
    from billing.credits import consume_credit

    return consume_credit(organization, user_id=user_id)