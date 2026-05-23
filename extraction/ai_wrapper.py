# extraction/ai_wrapper.py
import functools
import json
import logging
import os

from pydantic import BaseModel, ValidationError

from billing.models import AIUsageLog

# Bibliotecas das IAs
from google import genai
from google.genai import types
from groq import Groq
from openai import OpenAI

# Importa os schemas definidos por Juliano
from .schemas import ExtractedData, ServiceOrderSchema, SupportRequestSchema

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 2


@functools.lru_cache(maxsize=1)
def _get_openai_client() -> OpenAI:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY não está definida. Configure-a no ambiente ou no .env para usar o provedor OpenAI."
        )
    return OpenAI(api_key=key)


@functools.lru_cache(maxsize=1)
def _get_groq_client() -> Groq:
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY não está definida. Configure-a no ambiente ou no .env para usar o provedor Groq."
        )
    return Groq(api_key=key)


@functools.lru_cache(maxsize=1)
def _get_gemini_client() -> genai.Client:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY não está definida. Configure-a no ambiente ou no .env para usar o provedor Gemini."
        )
    return genai.Client(api_key=key)
  
  
  

def extract_fields_from_text(
    text: str, 
    schema: type[BaseModel], 
    prompt_template: str, 
    provider: str = 'OPENAI',
    examples: list = None
) -> dict | None:
    """
    Roteador universal para extração de dados com validação Pydantic.
    """
    schema_json = schema.model_json_schema()
    
    # 1. Montagem do Prompt de Sistema
    system_prompt = (
        "Você é um extrator de dados altamente eficiente. Sua única tarefa é analisar o texto "
        "fornecido e retornar os dados estritamente no formato JSON, conforme o schema abaixo. "
        f"Se não for possível preencher um campo, use `null` ou um valor padrão razoável.\n\n"
        f"SCHEMA JSON: {json.dumps(schema_json)}"
    )

    # 2. Montagem da Mensagem do Usuário
    user_prompt = f"{prompt_template}\n\nTEXTO DE ENTRADA:\n---\n{text}"
    
    # Estratégia de Fallback com Retries
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            logger.info(f"Tentativa {attempt + 1}: Chamando API {provider}...")
            
            # ROTEADOR DE IA
            if provider == 'OPENAI':
                raw_json_output = _call_openai(system_prompt, user_prompt)
            elif provider == 'GROQ':
                raw_json_output = _call_groq(system_prompt, user_prompt)
            elif provider == 'GEMINI':
                raw_json_output = _call_gemini(system_prompt, user_prompt)
            else:
                raise ValueError(f"Provedor de IA desconhecido: {provider}")

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
            logger.critical(f"Erro na comunicação com a API {provider}: {e}")
            break # Falha crítica de rede ou chave errada

    logger.error("Extração falhou após todas as tentativas. Retornando None.")
    return None

# --- FUNÇÕES INTERNAS DE CHAMADA ÀS APIS ---

def _call_openai(system_prompt, user_prompt):
    response = _get_openai_client().chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"} 
    )
    return response.choices[0].message.content

def _call_groq(system_prompt, user_prompt):
    response = _get_groq_client().chat.completions.create(
        model="llama-3.1-8b-instant", # NOVO: Modelo super-rápido atualizado
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content

def _call_gemini(system_prompt, user_prompt):
    # NOVO: Implementação com a biblioteca moderna google-genai
    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    response = _get_gemini_client().models.generate_content(
        model='gemini-2.5-flash', # <-- BASTA ALTERAR ISTO AQUI PARA A NOVA GERAÇÃO (Ou gemini-2.0-flash)
        contents=full_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    return response.text

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

def check_and_update_quota(organization):
    """ Verifica se o escritório ainda tem 'créditos' de IA este mês """
    from django.utils import timezone
    month_start = timezone.now().replace(day=1)
    
    usage, created = AIUsageLog.objects.get_or_create(
        organization=organization,
        billing_cycle_month=month_start
    )
    
    # Se o plano do escritório permitir menos extrações do que o contador atual
    if usage.extractions_count >= organization.plan.max_ai_extractions:
        return False, "Limite de extrações do seu plano atingido."
    
    # Incrementa o uso
    usage.extractions_count += 1
    usage.save()
    return True, ""