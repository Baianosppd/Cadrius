"""
Esquemas Pydantic e estruturas tipadas para o motor de workflows
(gatilhos, payloads de ação, validações de negócio).
"""
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    """
    Tipos de ação permitidos — manter alinhado com ``Action.ACTION_TYPES``
    em ``workflows.models``.
    """

    WEBHOOK = "WEBHOOK"
    WHATSAPP_EVOLUTION = "WHATSAPP_EVOLUTION"
    EMAIL_SMTP = "EMAIL_SMTP"


class TriggerSchema(BaseModel):
    """Representação tipada de um gatilho (espelho lógico do modelo ``Trigger``)."""

    event_type: str = Field(
        ...,
        max_length=100,
        description="Identificador do evento que dispara o fluxo (ex.: message_received).",
    )
    payload_mapping: dict[str, Any] = Field(
        default_factory=dict,
        description="Como mapear/normalizar o payload recebido para o motor (JSON).",
    )


class ActionSchema(BaseModel):
    """Representação tipada de uma ação (espelho lógico do modelo ``Action``)."""

    action_type: ActionType = Field(
        description="Tipo de integração a executar (mesmos códigos do modelo Django).",
    )
    endpoint_url: str | None = Field(
        default=None,
        description="URL alvo para WEBHOOK; opcional para outros tipos.",
    )
    payload_template: str = Field(
        ...,
        min_length=1,
        description="Template do corpo (ex.: JSON com marcadores {{chave}}).",
    )


class WorkflowGenerationSchema(BaseModel):
    """
    Esquema agregado: nome/descrição do fluxo, um gatilho e a lista de ações.
    Útil para APIs de criação em massa, IA a gerar workflows ou validação pré-gravação.
    """

    workflow_name: str = Field(
        ...,
        max_length=255,
        description="Nome do workflow apresentado no painel.",
    )
    workflow_description: str = Field(
        default="",
        description="Descrição opcional do fluxo (pode ser vazia).",
    )
    trigger: TriggerSchema = Field(
        description="Configuração do evento que inicia o fluxo.",
    )
    actions: list[ActionSchema] = Field(
        default_factory=list,
        description="Passos de saída a executar após o gatilho (ordem = ordem da lista).",
    )
