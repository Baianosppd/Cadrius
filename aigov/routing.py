"""IA por atividade (CAD-224): cada tipo de trabalho vai para o provedor que mais rende nele, com reservas automáticas.

Estudo e critérios em docs/ESTUDO_IA_POR_ATIVIDADE.md. Resumo da recomendação:
- automacao  — assistente com ferramentas, criação de regras/fluxos, conector MCP: precisa acertar chamadas de
               ferramenta em várias etapas → Claude primeiro (lidera o BFCL v4 de tool calling em 2026).
- estrategia — modo estratégia de caso (raciocínio longo, citação de fontes) → Claude, depois OpenAI.
- redacao    — minutas e ferramentas de texto em português jurídico → Sabiá (Maritaca: treinado em pt-BR, dados no
               Brasil, ~OAB 80%), depois Claude e OpenAI.
- extracao   — leitura de documentos/intimações para JSON validado → OpenAI (JSON estável e barato), Gemini pago, Claude.
- triagem    — classificação curta e em volume (e-mails) → Groq (Llama 70B, muito rápido e barato), Gemini, OpenAI.
- marketing  — texto institucional SEM dado de cliente (pode usar plano gratuito) → Gemini, Groq, Mistral, OpenAI.

Regras que nunca mudam com a configuração: sigilo (provedor que treina com os dados não recebe dado de cliente), política
de IA de cada escritório (provedores liberados) e chave própria do escritório primeiro (BYOK).
"""
from __future__ import annotations

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

ACTIVITIES = {
    'automacao': {'label': 'Automações e assistente (ferramentas)', 'needs_tools': True,
                  'recomendado': ['ANTHROPIC', 'OPENAI', 'GEMINI', 'MARITACA', 'GROQ', 'OLLAMA'],
                  'onde': 'Assistente IA, criação de regras e fluxos pela IA, conector Claude/ChatGPT.',
                  'por_que': 'Exige acertar chamadas de ferramenta em várias etapas; Claude lidera os testes de tool calling.'},
    'estrategia': {'label': 'Estratégia de caso', 'needs_tools': True,
                   'recomendado': ['ANTHROPIC', 'OPENAI', 'GEMINI', 'MARITACA'],
                   'onde': 'Modo estratégia de caso do assistente.',
                   'por_que': 'Raciocínio longo sobre o processo, com fontes; vale o modelo mais forte.'},
    'redacao': {'label': 'Redação jurídica e ferramentas de texto', 'needs_tools': False,
                'recomendado': ['MARITACA', 'ANTHROPIC', 'OPENAI', 'GEMINI', 'MISTRAL', 'GROQ', 'OLLAMA'],
                'onde': 'Minutas, corrigir/formalizar/resumir, e-mails e mensagens ao cliente.',
                'por_que': 'Português jurídico brasileiro: Sabiá é treinado em pt-BR, processa no Brasil e custa menos.'},
    'extracao': {'label': 'Leitura de documentos (extração)', 'needs_tools': False,
                 'recomendado': ['OPENAI', 'GEMINI', 'ANTHROPIC', 'GROQ', 'MARITACA', 'MISTRAL', 'OLLAMA'],
                 'onde': 'Leitura de documentos e intimações com prazos, partes e valores.',
                 'por_que': 'Precisa de JSON válido e estável em volume, com bom custo.'},
    'triagem': {'label': 'Triagem e classificação', 'needs_tools': False,
                'recomendado': ['GROQ', 'GEMINI', 'OPENAI', 'MARITACA', 'MISTRAL', 'OLLAMA'],
                'onde': 'Triagem de e-mails e classificações curtas.',
                'por_que': 'Muito volume e resposta curta: velocidade e custo mais que profundidade.'},
    'marketing': {'label': 'Marketing (conteúdo institucional)', 'needs_tools': False,
                  'recomendado': ['GEMINI', 'GROQ', 'MISTRAL', 'OPENAI', 'ANTHROPIC', 'MARITACA'],
                  'onde': 'Ideias e textos de marketing (sem dado de cliente).',
                  'por_que': 'Texto criativo e sem sigilo: pode usar planos gratuitos.'},
}
# perfis antigos (CAD-221) → atividade
LEGACY = {'assistente': 'automacao', 'economico': 'extracao'}
CACHE_KEY = 'aigov:routes'
FAIL_LIMIT, OPEN_SECONDS = 3, 300


def _routes() -> dict:
    data = cache.get(CACHE_KEY)
    if data is None:
        from aigov.models import AIRoute
        data = {r.activity: {'providers': r.providers, 'use_reserves': r.use_reserves} for r in AIRoute.objects.all()}
        cache.set(CACHE_KEY, data, 60)
    return data


def invalidate():
    cache.delete(CACHE_KEY)


def chain(activity: str) -> tuple[list[str], bool]:
    """(provedores em ordem, usar demais como reserva) para a atividade."""
    from aigov.llm import PROVIDERS
    activity = LEGACY.get(activity, activity)
    spec = ACTIVITIES.get(activity) or ACTIVITIES['extracao']
    route = _routes().get(activity)
    providers = route['providers'] if route and route['providers'] else spec['recomendado']
    return [p for p in providers if p in PROVIDERS], (route['use_reserves'] if route else True)


# ----------------------------------------------------------------------------- saúde dos provedores (disjuntor)
def _hkey(provider):
    return f'aigov:health:{provider}'


def record(provider: str, ok: bool, error: str = '') -> None:
    """Sucesso zera; 3 falhas seguidas "abrem o disjuntor" por 5 min (o provedor vai para o fim da fila)."""
    from django.utils import timezone
    h = cache.get(_hkey(provider)) or {'falhas': 0}
    now = timezone.now().isoformat()
    if ok:
        h = {'falhas': 0, 'ultimo_sucesso': now, 'ultimo_erro': h.get('ultimo_erro', ''), 'erro': h.get('erro', '')}
    else:
        h['falhas'] = h.get('falhas', 0) + 1
        h['ultimo_erro'], h['erro'] = now, error[:80]
        if h['falhas'] >= FAIL_LIMIT:
            cache.set(f'{_hkey(provider)}:open', 1, OPEN_SECONDS)
            logger.warning('IA: %s com %s falhas seguidas — vai para o fim da fila por %ss', provider, h['falhas'], OPEN_SECONDS)
    cache.set(_hkey(provider), h, 86400)


def is_open(provider: str) -> bool:
    return bool(cache.get(f'{_hkey(provider)}:open'))


def health(provider: str) -> dict:
    h = cache.get(_hkey(provider)) or {'falhas': 0}
    return {**h, 'fora_do_ar': is_open(provider)}


def reorder_by_health(providers: list[str]) -> list[str]:
    """Provedores com o disjuntor aberto vão para o fim (continuam como última tentativa)."""
    return [p for p in providers if not is_open(p)] + [p for p in providers if is_open(p)]


def overview() -> list[dict]:
    from aigov import llm
    out = []
    for key, spec in ACTIVITIES.items():
        providers, reserves = chain(key)
        safe = llm.candidates(None, sensitive=key != 'marketing', need_tools=spec['needs_tools'], profile=key)
        out.append({'atividade': key, 'rotulo': spec['label'], 'onde': spec['onde'], 'por_que': spec['por_que'],
                    'cadeia': providers, 'usar_reservas': reserves, 'recomendado': spec['recomendado'],
                    'personalizado': key in _routes(), 'precisa_ferramentas': spec['needs_tools'],
                    'atende_agora': safe[0] if safe else None, 'ordem_efetiva': safe})
    return out
