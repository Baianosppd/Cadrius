"""
Ponto único para ligar a fila de execução (django-q, Celery, etc.).

Não dispara processamento aqui — implementação futura substitui o corpo desta função.
"""

from __future__ import annotations

from typing import Any


def enqueue_webhook_for_execution(prepared: dict[str, Any]) -> None:
    """
    Recebe o pacote já validado e pronto para a fila.

    Campos esperados em `prepared` (contrato estável para o motor):
    - workflow_id
    - trigger_id
    - payload (dict)
    - received_at (ISO 8601)

    Para ativar a fila, implemente o corpo desta função (ex.: async_task(...)).
    """
    # Intencionalmente vazio: não acoplar a django-q/celery nesta camada.
    return None
