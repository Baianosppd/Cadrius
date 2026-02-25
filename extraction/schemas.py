from pydantic import BaseModel, Field, conint
from datetime import date
from typing import Literal
 

# --- Base Schemas para o Projeto ---

class ExtractedData(BaseModel):
    """
    Schema base para todos os dados extraídos, garantindo campos comuns de controle.
    """
    # Identifica o tipo de documento que a IA reconheceu no email
    document_type: Literal['SERVICE_ORDER', 'SUPPORT_REQUEST', 'REPORT', 'OTHER'] = Field(
        description="O tipo de documento detectado (Ex: Pedido de Serviço, Solicitação de Suporte)."
    )
    # Razoabilidade - Confiança da IA na extração (0-100)
    confidence_score: conint(ge=0, le=100) = Field(
        description="Pontuação de confiança da IA na extração dos dados (0 a 100)."
    )


class ProcessoJuridicoSchema(ExtractedData):
    """
    Schema para extrair dados de e-mails de movimentação processual.
    """
    document_type: Literal['MOVIMENTACAO_PROCESSUAL']

    numero_processo: str = Field(
        description="Número único do processo, no formato NNNNNNN-DD.AAAA.J.TR.OOOO."
    )
    
    tipo_movimentacao: str = Field(
        description="Tipo de documento ou ato processual (ex: Intimação, Despacho, Decisão, Sentença)."
    )

    resumo_movimentacao: str = Field(
        description="Um resumo curto e objetivo do que se trata a movimentação."
    )

    prazo_fatal: date | None = Field(
        default=None, 
        description="A data final para o cumprimento do prazo, se houver. Formato: AAAA-MM-DD."
    )

    sugestao_proximo_passo: str = Field(
        description="Sugestão de ação clara e objetiva para o advogado (ex: 'Preparar recurso de apelação', 'Dar ciência', 'Agendar pagamento de custas')."
    )

# --- 1. Exemplo de Pedido de Serviço (SERVICE_ORDER) ---

class ServiceOrderSchema(ExtractedData):
    """
    Schema de Pydantic para extrair informações de um Pedido de Serviço.
    """
    # Sobrescreve o tipo base
    document_type: Literal['SERVICE_ORDER']

    customer_name: str = Field(description="Nome completo ou Razão Social do cliente.")
    service_description: str = Field(description="Descrição detalhada do serviço solicitado.")
    priority: Literal['HIGH', 'MEDIUM', 'LOW'] = Field(description="Prioridade sugerida para o atendimento.")
    target_sla_days: conint(ge=1, le=90) = Field(
        description="Prazo de entrega (SLA) sugerido em dias úteis."
    )
    delivery_date: date | None = Field(
        default=None, description="Data limite de entrega (se explicitada no email)."
    )
    contact_phone: str = Field(description="Telefone de contato preferencial do cliente.")


# --- 2. Exemplo de Solicitação de Suporte (SUPPORT_REQUEST) ---

class SupportRequestSchema(ExtractedData):
    """
    Schema de Pydantic para extrair informações de uma Solicitação de Suporte/Bug.
    """
    # Sobrescreve o tipo base
    document_type: Literal['SUPPORT_REQUEST']

    system_affected: str = Field(description="O nome do sistema ou módulo afetado (Ex: Financeiro, CRM, Website).")
    issue_summary: str = Field(description="Resumo conciso do problema ou erro.")
    is_critical: bool = Field(description="Verdadeiro se o problema impedir a operação normal do cliente.")
    error_code: str | None = Field(default=None, description="Qualquer código de erro mencionado.")
    requester_email: str = Field(description="Email de quem enviou a solicitação (para follow-up).")