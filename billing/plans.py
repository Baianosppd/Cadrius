"""Apresentação dos planos para o front (BILLING-01)."""
from __future__ import annotations

from billing.models import SubscriptionPlan


def format_plan_price(plan: SubscriptionPlan) -> str:
    if plan.price_brl == 0:
        return 'Grátis'
    price = plan.price_brl
    if price == int(price):
        return f'R$ {int(price)}'
    formatted = f'{price:.2f}'.replace('.', ',')
    return f'R$ {formatted}'


def plan_description(plan: SubscriptionPlan) -> str:
    if plan.tier in ('FREE', 'START'):
        return f'Limite de {plan.max_ai_extractions} documentos/mês'
    if plan.tier == 'PRO':
        return ''
    if plan.tier == 'ENTERPRISE':
        return 'Solução completa para operações em escala.'
    return f'Até {plan.max_ai_extractions} extrações com IA por mês.'


def plan_features(plan: SubscriptionPlan) -> list[str]:
    if plan.tier in ('FREE', 'START'):
        return []

    credits = f'{plan.max_ai_extractions:,}'.replace(',', '.')
    features = [f'{credits} créditos']

    if plan.tier == 'PRO':
        features.extend([
            'Gestão de Tarefas',
            f'Até {plan.max_users} usuários',
            'Integrações premium',
        ])
    elif plan.tier == 'ENTERPRISE':
        features.extend([
            'Gestão de Tarefas',
            f'Até {plan.max_users} usuários',
            'Integrações premium',
            'Suporte prioritário',
        ])

    return features
