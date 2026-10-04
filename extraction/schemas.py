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

class ParteSchema(BaseModel):
    papel: str = Field(description="Papel da parte (ex.: Autor, Réu, Contratante, Contratado, Advogado).")
    nome: str = Field(description="Nome ou razão social. CPF/CNPJ/telefone/e-mail já vêm mascarados no texto: não os invente.")


class PrazoSchema(BaseModel):
    descricao: str = Field(description="O que precisa ser feito (ex.: 'Contestação', 'Apresentar documentos').")
    data: date | None = Field(default=None, description="Data limite, se constar no texto. Formato AAAA-MM-DD.")
    dias: int | None = Field(default=None, description="Prazo em dias, se o texto fala em dias e não em data.")
    fatal: bool = Field(default=False, description="Verdadeiro se o texto indicar prazo fatal/peremptório.")


class DocumentoJuridicoSchema(ExtractedData):
    """Leitura de qualquer documento jurídico anexado (petição, decisão, contrato, procuração...). O advogado SEMPRE revisa o resultado."""

    document_type: Literal['DOCUMENTO_JURIDICO']

    tipo_documento: Literal['PETICAO', 'SENTENCA', 'DECISAO', 'INTIMACAO', 'CONTRATO', 'PROCURACAO', 'CERTIDAO', 'OUTRO'] = Field(
        description="Classificação do documento.")
    numero_processo: str | None = Field(default=None, description="Número CNJ do processo (NNNNNNN-DD.AAAA.J.TR.OOOO), se houver.")
    partes: list[ParteSchema] = Field(default_factory=list, description="Partes e papéis identificados.")
    resumo: str = Field(description="Resumo objetivo em até 5 linhas, em linguagem simples.")
    prazos: list[PrazoSchema] = Field(default_factory=list, description="Prazos e datas relevantes. Não invente: só o que está no texto.")
    valor: str | None = Field(default=None, description="Valor da causa/contrato, como aparece no texto.")
    proximos_passos: list[str] = Field(default_factory=list, description="Ações sugeridas ao advogado.")


# --- 1. Exemplo de Pedido de Serviço (SERVICE_ORDER) ---

class ServiceOrderSchema(ExtractedData):
    """
    Schema de Pydantic para extrair informações de um Pedido de Serviço.
    """
    
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


def get_extraction_schema(name: str):
    """
    Resolve o nome gravado em ``ExtractionProfile.pydantic_schema_name`` para uma classe.

    Só aceita subclasses de ``ExtractedData`` deste módulo — antes qualquer atributo do módulo
    (ex.: ``date``, ``BaseModel``) podia ser escolhido por um utilizador.
    """
    candidate = globals().get(name or "")
    if isinstance(candidate, type) and issubclass(candidate, ExtractedData):
        return candidate
    return None


def list_extraction_schemas() -> list[str]:
    return sorted(
        n for n, v in globals().items()
        if isinstance(v, type) and issubclass(v, ExtractedData) and v is not ExtractedData
    )
