"""Peso (em créditos) de cada operação de IA — editável pelo financeiro (CreditWeight); estes são os padrões da análise de preços."""
DEFAULT_WEIGHTS = {
    'extraction': ('Extração de documento', 1),
    'triage': ('Triagem/classificação (modelo pequeno/local)', 0),
    'summary': ('Resumo de andamento ou publicação', 1),
    'automation_draft': ('Rascunho de automação por IA', 2),
    'research_summary': ('Pesquisa jurisprudencial com resumo', 3),
    'draft_petition': ('Minuta de peça', 15),
    'marketing_content': ('Conteúdo de marketing com IA', 2),
    'ocr_page': ('OCR de página escaneada (local)', 0),
    'assistant_message': ('Mensagem ao assistente de IA', 1),
    'writing': ('Corrigir, reescrever ou resumir texto com IA', 1),
}


def credits_for(operation: str) -> int:
    """Créditos a cobrar pela operação. Operação inativa/desconhecida cai no padrão (ou 1)."""
    from billing.models import CreditWeight
    row = CreditWeight.objects.filter(operation=operation, is_active=True).values_list('credits', flat=True).first()
    if row is not None:
        return row
    return DEFAULT_WEIGHTS.get(operation, ('', 1))[1]


def ensure_default_weights():
    from billing.models import CreditWeight
    for op, (label, credits) in DEFAULT_WEIGHTS.items():
        CreditWeight.objects.get_or_create(operation=op, defaults={'label': label, 'credits': credits})
