import os
import json
import logging
from openai import OpenAI
from pydantic import BaseModel, ValidationError

# Importa os schemas definidos por Juliano
from .schemas import ExtractedData, ServiceOrderSchema, SupportRequestSchema 

logger = logging.getLogger(__name__)

# Configuração do cliente OpenAI (lê a chave do settings.py via os.environ)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
AI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")

# Número máximo de tentativas de re-prompt antes de falhar
MAX_RETRY_ATTEMPTS = 2


def extract_fields_from_text(
    text: str, 
    schema: type[BaseModel], 
    prompt_template: str, 
    examples: list = None
) -> dict | None:
    """
    Extrai dados estruturados de um texto usando a API do OpenAI e valida com Pydantic.

    Args:
        text: O corpo do email a ser analisado.
        schema: O modelo Pydantic (ex: ServiceOrderSchema) para validação.
        prompt_template: O template de instrução para a IA.
        examples: Exemplos few-shot para guiar a extração (opcional).

    Returns:
        Um dicionário Python (JSON validado) ou None em caso de falha.
    """
    schema_json = schema.model_json_schema()
    
    # 1. Montagem do Prompt de Sistema (Instruções e Estrutura JSON)
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
            logger.info(f"Tentativa {attempt + 1}: Chamando API OpenAI...")
            
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    # Adicionar exemplos few-shot aqui, se houver
                    {"role": "user", "content": user_prompt}
                ],
                # Força a saída como JSON (necessita do modelo gpt-3.5-turbo ou superior)
                response_format={"type": "json_object"} 
            )

            raw_json_output = response.choices[0].message.content
            
            # 3. VALIDAÇÃO PYDANTIC (CRÍTICO)
            # Converte a string JSON para o modelo Pydantic, que valida tipos e restrições.
            validated_model = schema.model_validate_json(raw_json_output)
            
            # Retorna o modelo validado como um dicionário Python
            return validated_model.model_dump(mode='json')

        except json.JSONDecodeError:
            logger.error(f"Tentativa {attempt + 1}: Resposta da IA não é um JSON válido.")
            user_prompt += "\nA saída anterior não foi um JSON válido. Por favor, corrija e retorne APENAS o JSON."
            
        except ValidationError as e:
            logger.error(f"Tentativa {attempt + 1}: Falha na validação Pydantic. Erro: {e}")
            # Se a validação falha, Juliano instrui a IA a tentar corrigir o JSON.
            error_message = f"O JSON retornado falhou na validação. Erros:\n{e}"
            user_prompt += f"\nCorrija os erros de schema no seu JSON:\n{error_message}"

        except Exception as e:
            logger.critical(f"Erro na comunicação com a API OpenAI: {e}")
            break # Falha crítica, não tentar novamente.

    # 4. FALLBACK FINAL: Marcação para Revisão Humana
    logger.error("Extração falhou após todas as tentativas. Retornando None.")
    return None

# --------------------------------------------------------------------------------
# MOCK DE TESTE (A ser usado por Juliano para testes unitários em CI)
# --------------------------------------------------------------------------------

def mock_extract_fields_from_text(text: str, schema: type[BaseModel], **kwargs) -> dict | None:
    """
    Simula a extração de IA para testes em ambientes onde a chave API não está disponível.
    """
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

# No código de Juliano, ele pode usar uma variável de ambiente para chavear 
# entre a função real e o mock durante os testes!.
