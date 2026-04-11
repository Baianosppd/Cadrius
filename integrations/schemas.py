from pydantic import BaseModel, Field
from typing import Optional

class AstreaWebhookPayload(BaseModel):
    """
    Molde básico do que o CRM Astrea envia num Webhook de 'Novo Andamento'
    """
    event_type: str = Field(..., description="Tipo de evento, ex: andamento.criado")
    processo_id: str = Field(..., description="ID interno do processo no Astrea")
    numero_cnj: Optional[str] = None
    descricao_andamento: str = Field(..., description="O texto da publicação ou andamento")
    data_criacao: str