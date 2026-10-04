#!/usr/bin/env python3
"""Modelo de preços/margem do Cadrius (CAD-119). Sem dependências: python3 scripts/pricing_model.py [--md]

TODOS os números abaixo são PREMISSAS editáveis (preços de IA e taxas mudam): confirme nos painéis dos provedores,
no contrato do Stripe e com o contador antes de fixar preços. O objetivo é mostrar a *estrutura* da conta.
"""
from __future__ import annotations

import sys

# ----------------------------------------------------------------------------- premissas
USD_BRL = 5.60                       # câmbio
# preço por 1M de tokens (USD): (entrada, saída)  — CONFIRMAR nos painéis
MODELS = {
    'groq llama-3.1-8b':   (0.05, 0.08),
    'gemini-2.5-flash':    (0.30, 2.50),
    'openai gpt-4o-mini':  (0.15, 0.60),
    'openai gpt-3.5-turbo (atual)': (0.50, 1.50),
    'modelo premium (peças)':       (3.00, 15.00),
}
STRIPE_PCT, STRIPE_FIXED = 0.0399, 0.39   # cartão nacional (confirmar contrato)
TAX_PCT = 0.08                       # imposto sobre receita (Simples Nacional, faixa a confirmar com o contador)
FIXED_MONTHLY = {                    # custos fixos do sistema (R$/mês) — substituir pelos reais
    'VPS (produção + teste)': 450, 'Backup externo (Supabase/Storage)': 130, 'E-mail transacional': 100,
    'Sentry/monitoramento': 150, 'Domínio, certificados, ferramentas': 80, 'IA local (CPU, embeddings/triagem)': 0,
}
SUPPORT_RATE_H = 60                  # custo da hora de suporte (R$)

# Operações e seus pesos em CRÉDITOS (1 crédito = 1 extração padrão). Tokens médios (entrada, saída) e modelo usado.
OPS = {
    'extração de documento':         dict(credits=1,  tin=6000,  tout=1000, model='gemini-2.5-flash'),
    'triagem/classificação':         dict(credits=0.2, tin=1500, tout=100,  model='groq llama-3.1-8b'),
    'resumo de andamento/publicação': dict(credits=1,  tin=3000,  tout=500,  model='openai gpt-4o-mini'),
    'rascunho de automação (IA)':    dict(credits=2,  tin=2500,  tout=1500, model='gemini-2.5-flash'),
    'pesquisa jurisprudencial c/ resumo': dict(credits=3, tin=12000, tout=1500, model='gemini-2.5-flash'),
    'minuta de peça':                dict(credits=15, tin=20000, tout=4000, model='modelo premium (peças)'),
}

# plano: preço, usuários, créditos/mês, horas de suporte/mês estimadas por cliente
PLANS = {
    'START (solo)':        dict(price=99,  users=1,  credits=300,  support_h=0.25),
    'PRO (escritório)':    dict(price=299, users=5,  credits=1500, support_h=0.75),
    'BUSINESS (grande)':   dict(price=799, users=20, credits=6000, support_h=2.0),
}
PACKS = {'200 créditos': (200, 59.0), '1.000 créditos': (1000, 199.0), '5.000 créditos': (5000, 799.0)}
# mistura de uso típica (fração dos créditos consumidos por operação) — pior caso usa 'peças' pesado
MIX_TYPICAL = {'extração de documento': 0.55, 'triagem/classificação': 0.10, 'resumo de andamento/publicação': 0.20,
               'rascunho de automação (IA)': 0.05, 'pesquisa jurisprudencial c/ resumo': 0.07, 'minuta de peça': 0.03}
MIX_HEAVY = {'extração de documento': 0.30, 'triagem/classificação': 0.05, 'resumo de andamento/publicação': 0.15,
             'rascunho de automação (IA)': 0.05, 'pesquisa jurisprudencial c/ resumo': 0.15, 'minuta de peça': 0.30}


def cost_brl(op: dict) -> float:
    pin, pout = MODELS[op['model']]
    return (op['tin'] * pin + op['tout'] * pout) / 1_000_000 * USD_BRL


def cogs_per_credit(mix: dict) -> float:
    """Custo real de IA (R$) por crédito vendido, dada a mistura de operações."""
    cost = sum(share * cost_brl(OPS[name]) / OPS[name]['credits'] for name, share in mix.items())
    return cost  # share é fração dos CRÉDITOS; custo/crédito da operação = custo_op / créditos_op


def plan_margin(plan: dict, util: float, mix: dict, customers: int = 1):
    revenue = plan['price']
    fees = revenue * STRIPE_PCT + STRIPE_FIXED
    tax = revenue * TAX_PCT
    ai = plan['credits'] * util * cogs_per_credit(mix)
    support = plan['support_h'] * SUPPORT_RATE_H
    contribution = revenue - fees - tax - ai - support
    return dict(revenue=revenue, fees=fees, tax=tax, ai=ai, support=support, contribution=contribution,
                margin=contribution / revenue)


def main(md=False):
    out = []
    p = out.append
    p(f'Câmbio: R$ {USD_BRL:.2f}/US$ · Stripe {STRIPE_PCT:.2%} + R$ {STRIPE_FIXED:.2f} · imposto {TAX_PCT:.0%}\n')
    p('## Custo de IA por operação (R$)')
    p('| Operação | Créditos | Modelo | Custo R$ | Custo/crédito R$ |')
    p('|---|---:|---|---:|---:|')
    for name, op in OPS.items():
        p(f"| {name} | {op['credits']:g} | {op['model']} | {cost_brl(op):.4f} | {cost_brl(op) / op['credits']:.4f} |")
    p('')
    p(f"Custo médio por crédito — mistura típica: R$ {cogs_per_credit(MIX_TYPICAL):.4f} · mistura pesada: R$ {cogs_per_credit(MIX_HEAVY):.4f}\n")
    p('## Troca do modelo da extração padrão (6.000 tokens entrada + 1.000 saída)')
    p('| Modelo | R$/extração |')
    p('|---|---:|')
    for m in ('groq llama-3.1-8b', 'openai gpt-4o-mini', 'gemini-2.5-flash', 'openai gpt-3.5-turbo (atual)'):
        pin, pout = MODELS[m]
        p(f'| {m} | {(6000 * pin + 1000 * pout) / 1e6 * USD_BRL:.4f} |')
    p('')
    p('## Margem de contribuição por cliente/mês (depois de Stripe, imposto, IA e suporte)')
    p('| Plano | Preço | Uso dos créditos | Mistura | IA R$ | Contribuição R$ | Margem |')
    p('|---|---:|---:|---|---:|---:|---:|')
    for name, plan in PLANS.items():
        for util in (0.3, 0.7, 1.0):
            for mix_name, mix in (('típica', MIX_TYPICAL), ('pesada', MIX_HEAVY)):
                if mix_name == 'pesada' and util != 1.0:
                    continue
                m = plan_margin(plan, util, mix)
                p(f"| {name} | {plan['price']} | {util:.0%} | {mix_name} | {m['ai']:.2f} | {m['contribution']:.2f} | {m['margin']:.0%} |")
    p('')
    p('## Pacotes de créditos avulsos (compra extra; validade 12 meses)')
    p('| Pacote | Preço | R$/crédito | Custo IA (mistura pesada) | Margem após taxas+imposto |')
    p('|---|---:|---:|---:|---:|')
    for name, (credits, price) in PACKS.items():
        ai = credits * cogs_per_credit(MIX_HEAVY)
        net = price - (price * STRIPE_PCT + STRIPE_FIXED) - price * TAX_PCT - ai
        p(f'| {name} | {price:.0f} | {price / credits:.3f} | {ai:.2f} | {net / price:.0%} |')
    p('')
    fixed = sum(FIXED_MONTHLY.values())
    p(f'## Ponto de equilíbrio (custos fixos R$ {fixed:,.0f}/mês)'.replace(',', '.'))
    p('| Mix de clientes | Contribuição/mês | Clientes p/ cobrir o fixo |')
    p('|---|---:|---:|')
    for label, weights in (('só START', {'START (solo)': 1}), ('só PRO', {'PRO (escritório)': 1}),
                           ('60% START / 35% PRO / 5% BUSINESS', {'START (solo)': .6, 'PRO (escritório)': .35, 'BUSINESS (grande)': .05})):
        avg = sum(w * plan_margin(PLANS[n], 0.7, MIX_TYPICAL)['contribution'] for n, w in weights.items())
        p(f'| {label} | {avg:.0f} | {fixed / avg:.1f} |')
    print('\n'.join(out))


if __name__ == '__main__':
    main(md='--md' in sys.argv)
