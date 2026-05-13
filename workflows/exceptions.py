"""Exceções de domínio da app workflows."""


class WorkflowGenerationQuotaExceeded(Exception):
    """Limite de IA do plano do escritório atingido (antes ou durante o abate de quota)."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)
