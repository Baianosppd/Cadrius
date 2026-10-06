"""Camada única de IA (CAD-221): vários provedores atrás de uma interface só, com roteamento por política e sigilo.

Provedores:
- Compatíveis com a API da OpenAI (SDK ``openai`` com ``base_url``): OpenAI, Gemini, Groq, Mistral, Maritaca (Sabiá),
  OpenRouter e Ollama (modelo local, no próprio servidor).
- Claude (Anthropic) pelo SDK oficial ``anthropic``.

Sigilo profissional / LGPD: planos GRATUITOS de alguns provedores usam o que é enviado para treinar modelos (ex.: Gemini
free, Mistral Experiment, modelos ``:free`` do OpenRouter). Esses provedores só recebem pedidos marcados como
``sensitive=False`` (ex.: marketing institucional, perguntas genéricas), a menos que a conta seja paga
(``<PROVEDOR>_PAID=true`` no .env). Dado de cliente nunca vai para quem treina com ele.

Nenhuma chave aparece em log, resposta de API ou tela: só "configurado sim/não".
"""
from __future__ import annotations

import functools
import json
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    kind: str                      # 'openai' (compatível) | 'anthropic'
    key_env: str = ''              # vazio = não precisa de chave (Ollama)
    base_url: str = ''
    base_url_env: str = ''
    model_env: str = ''
    default_model: str = ''
    tools: bool = True             # aceita chamada de ferramentas (assistente)
    free_tier: str = ''            # descrição do plano gratuito (vazio = pago)
    trains_on_free: bool = False   # o plano gratuito usa os dados para treinar?
    paid_env: str = ''             # <PROVEDOR>_PAID=true → conta paga (sem treino)
    local: bool = False            # roda no nosso servidor (dado não sai)
    region: str = ''
    site: str = ''


PROVIDERS: dict[str, Provider] = {p.key: p for p in [
    Provider('ANTHROPIC', 'Claude (Anthropic)', 'anthropic', 'ANTHROPIC_API_KEY', model_env='ANTHROPIC_MODEL',
             default_model='claude-opus-5-5', region='EUA', site='https://www.anthropic.com/pricing'),
    Provider('OPENAI', 'OpenAI (ChatGPT)', 'openai', 'OPENAI_API_KEY', model_env='OPENAI_MODEL',
             default_model='gpt-4o-mini', region='EUA', site='https://openai.com/api/pricing/'),
    Provider('GEMINI', 'Google Gemini', 'openai', 'GEMINI_API_KEY',
             base_url='https://generativelanguage.googleapis.com/v1beta/openai/', model_env='GEMINI_MODEL',
             default_model='gemini-2.5-flash', free_tier='Flash e Flash-Lite grátis com limite diário',
             trains_on_free=True, paid_env='GEMINI_PAID', region='EUA', site='https://ai.google.dev/pricing'),
    Provider('MARITACA', 'Maritaca Sabiá (Brasil)', 'openai', 'MARITACA_API_KEY', base_url='https://chat.maritaca.ai/api',
             model_env='MARITACA_MODEL', default_model='sabia-3.1', region='Brasil', site='https://www.maritaca.ai/api'),
    Provider('MISTRAL', 'Mistral AI', 'openai', 'MISTRAL_API_KEY', base_url='https://api.mistral.ai/v1',
             model_env='MISTRAL_MODEL', default_model='mistral-small-latest',
             free_tier='Plano Experiment gratuito (telefone verificado), com limite de taxa', trains_on_free=True,
             paid_env='MISTRAL_PAID', region='União Europeia', site='https://mistral.ai/pricing'),
    Provider('GROQ', 'Groq (Llama)', 'openai', 'GROQ_API_KEY', base_url='https://api.groq.com/openai/v1',
             model_env='GROQ_MODEL', default_model='llama-3.3-70b-versatile',
             free_tier='Gratuito com limite por minuto e por dia', region='EUA', site='https://groq.com/pricing'),
    Provider('OPENROUTER', 'OpenRouter (vários modelos)', 'openai', 'OPENROUTER_API_KEY', base_url='https://openrouter.ai/api/v1',
             model_env='OPENROUTER_MODEL', default_model='meta-llama/llama-3.3-70b-instruct:free',
             free_tier='Modelos ":free" com 50 pedidos/dia (1.000 após comprar créditos)', trains_on_free=True,
             paid_env='OPENROUTER_PAID', region='varia por modelo', site='https://openrouter.ai/models'),
    Provider('OLLAMA', 'Modelo local (Ollama)', 'openai', '', base_url_env='OLLAMA_BASE_URL', model_env='OLLAMA_MODEL',
             default_model='qwen2.5:7b-instruct', free_tier='Gratuito: roda no próprio servidor', local=True,
             region='servidor do Cadrius', site='https://ollama.com/library'),
]}

# Ordem de preferência por perfil de tarefa (sobrescreva no .env com a lista separada por vírgula):
# - 'economico' (extração, triagem, minuta, marketing): barato primeiro — docs/ANALISE_PRECOS_PLANOS.md §5 (AI_PROVIDER_ORDER)
# - 'assistente' (conversa com ferramentas): qualidade primeiro (AI_ASSISTANT_PROVIDER_ORDER)
ORDERS = {
    'economico': ('AI_PROVIDER_ORDER', ('GROQ', 'GEMINI', 'MARITACA', 'MISTRAL', 'OPENAI', 'ANTHROPIC', 'OPENROUTER', 'OLLAMA')),
    'assistente': ('AI_ASSISTANT_PROVIDER_ORDER', ('ANTHROPIC', 'OPENAI', 'GEMINI', 'MARITACA', 'MISTRAL', 'GROQ', 'OPENROUTER', 'OLLAMA')),
}


class LLMError(Exception):
    """Nenhum provedor disponível ou todos falharam (mensagem segura para o usuário)."""


def _env(name: str) -> str:
    return (os.environ.get(name) or '').strip() if name else ''


def base_url(p: Provider) -> str:
    return _env(p.base_url_env) or p.base_url


def model_for(p: Provider) -> str:
    return _env(p.model_env) or p.default_model


def configured(key: str) -> bool:
    p = PROVIDERS.get(key)
    if not p:
        return False
    if p.local:
        return bool(_env(p.base_url_env))
    return bool(_env(p.key_env))


def may_train(key: str) -> bool:
    """O provedor pode usar o conteúdo para treinar modelos (plano gratuito sem opção paga ativada)?"""
    p = PROVIDERS[key]
    if not p.trains_on_free:
        return False
    if key == 'OPENROUTER':
        return model_for(p).endswith(':free') and _env(p.paid_env).lower() != 'true'
    return _env(p.paid_env).lower() != 'true'


def order(profile: str = 'economico') -> list[str]:
    env_name, default = ORDERS.get(profile, ORDERS['economico'])
    wanted = [k.strip().upper() for k in _env(env_name).split(',') if k.strip()]
    seen = [k for k in wanted if k in PROVIDERS]
    return seen + [k for k in default if k not in seen]


def candidates(allowed=None, *, sensitive: bool = True, need_tools: bool = False, profile: str = 'economico') -> list[str]:
    """Provedores utilizáveis, na ordem de preferência: configurados, permitidos pela política e seguros para o dado."""
    out = []
    for key in order(profile):
        p = PROVIDERS[key]
        if allowed is not None and key not in allowed:
            continue
        if not configured(key) or (need_tools and not p.tools):
            continue
        if sensitive and may_train(key):
            continue
        out.append(key)
    return out


def catalog(allowed=None) -> list[dict]:
    """Situação de cada provedor para as telas (sem segredo)."""
    return [{
        'chave': p.key, 'nome': p.label, 'configurado': configured(p.key), 'permitido': allowed is None or p.key in allowed,
        'modelo': model_for(p), 'gratuito': p.free_tier, 'treina_com_dados': may_train(p.key), 'local': p.local,
        'regiao': p.region, 'site': p.site, 'ferramentas': p.tools,
    } for p in (PROVIDERS[k] for k in order('assistente'))]


# ----------------------------------------------------------------------------- clientes
@functools.lru_cache(maxsize=16)
def _openai_client(key: str, url: str, api_key: str):
    from openai import OpenAI
    return OpenAI(api_key=api_key or 'ollama', base_url=url or None, timeout=90, max_retries=1)


@functools.lru_cache(maxsize=4)
def _anthropic_client(api_key: str):
    import anthropic
    return anthropic.Anthropic(api_key=api_key, timeout=120, max_retries=1)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    text: str
    provider: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: object = None             # conteúdo original do provedor (reenviado no mesmo laço de ferramentas)


# Mensagens no formato neutro:
#   {'role': 'user'|'assistant', 'content': str}
#   {'role': 'assistant', 'content': str, 'tool_calls': [ToolCall...], 'raw': <conteúdo do provedor>, 'provider': KEY}
#   {'role': 'tool', 'tool_call_id': id, 'name': nome, 'content': str}
# Ferramentas: {'name', 'description', 'parameters': JSON Schema}

def _to_openai(system: str, messages: list[dict]) -> list[dict]:
    out = [{'role': 'system', 'content': system}] if system else []
    for m in messages:
        if m['role'] == 'tool':
            out.append({'role': 'tool', 'tool_call_id': m['tool_call_id'], 'content': m['content']})
        elif m['role'] == 'assistant' and m.get('tool_calls'):
            out.append({'role': 'assistant', 'content': m.get('content') or None, 'tool_calls': [
                {'id': c.id, 'type': 'function', 'function': {'name': c.name, 'arguments': json.dumps(c.arguments, ensure_ascii=False)}}
                for c in m['tool_calls']]})
        else:
            out.append({'role': m['role'], 'content': m.get('content') or ''})
    return out


def _call_openai_compat(p: Provider, system, messages, tools, json_mode, max_tokens) -> Reply:
    client = _openai_client(p.key, base_url(p), _env(p.key_env))
    kwargs = {'model': model_for(p), 'messages': _to_openai(system, messages), 'max_tokens': max_tokens}
    if tools:
        kwargs['tools'] = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                                                             'parameters': t['parameters']}} for t in tools]
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    calls = []
    for c in msg.tool_calls or []:
        try:
            args = json.loads(c.function.arguments or '{}')
        except json.JSONDecodeError:
            args = {}
        calls.append(ToolCall(c.id, c.function.name, args if isinstance(args, dict) else {}))
    return Reply(msg.content or '', p.key, kwargs['model'], calls)


def _to_anthropic(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m['role'] == 'tool':
            block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
            if out and out[-1]['role'] == 'user' and isinstance(out[-1]['content'], list) \
                    and all(b.get('type') == 'tool_result' for b in out[-1]['content']):
                out[-1]['content'].append(block)      # todos os resultados numa única mensagem
            else:
                out.append({'role': 'user', 'content': [block]})
        elif m['role'] == 'assistant' and m.get('tool_calls'):
            if m.get('provider') == 'ANTHROPIC' and m.get('raw') is not None:
                out.append({'role': 'assistant', 'content': m['raw']})   # reenviado sem edição
            else:
                blocks = [{'type': 'text', 'text': m['content']}] if m.get('content') else []
                blocks += [{'type': 'tool_use', 'id': c.id, 'name': c.name, 'input': c.arguments} for c in m['tool_calls']]
                out.append({'role': 'assistant', 'content': blocks})
        else:
            out.append({'role': m['role'], 'content': m.get('content') or ''})
    return out


def _call_anthropic(p: Provider, system, messages, tools, json_mode, max_tokens) -> Reply:
    import anthropic
    client = _anthropic_client(_env(p.key_env))
    model = model_for(p)
    if json_mode:
        system = f'{system}\n\nResponda APENAS com um objeto JSON válido, sem texto antes ou depois.'
    kwargs = {'model': model, 'max_tokens': max_tokens, 'system': system, 'messages': _to_anthropic(messages)}
    if tools:
        kwargs['tools'] = [{'name': t['name'], 'description': t['description'], 'input_schema': t['parameters']} for t in tools]
    try:
        resp = client.messages.create(**kwargs)
    except anthropic.APIStatusError as exc:
        raise LLMError(f'Claude respondeu com erro {exc.status_code}.') from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError('Sem conexão com o Claude.') from exc
    if resp.stop_reason == 'refusal':
        return Reply('O modelo recusou este pedido.', p.key, model)
    text = ''.join(b.text for b in resp.content if b.type == 'text')
    calls = [ToolCall(b.id, b.name, dict(b.input or {})) for b in resp.content if b.type == 'tool_use']
    return Reply(text, p.key, model, calls, raw=resp.content)


def call(provider: str, *, system: str, messages: list[dict], tools=None, json_mode=False, max_tokens=4096) -> Reply:
    p = PROVIDERS[provider]
    if not configured(provider):
        raise LLMError(f'{p.label} não está configurado.')
    if p.kind == 'anthropic':
        return _call_anthropic(p, system, messages, tools, json_mode, max_tokens)
    return _call_openai_compat(p, system, messages, tools, json_mode, max_tokens)


def complete_json(provider: str, system: str, user: str) -> str:
    """Texto JSON (usado pelo extrator com validação Pydantic)."""
    return call(provider, system=system, messages=[{'role': 'user', 'content': user}], json_mode=True).text


def chat_with_fallback(providers: list[str], **kwargs) -> Reply:
    """Tenta cada provedor na ordem; registra a falha (sem conteúdo) e passa ao próximo."""
    if not providers:
        raise LLMError('Nenhum provedor de IA permitido e configurado para este pedido.')
    last = None
    for key in providers:
        try:
            return call(key, **kwargs)
        except Exception as exc:  # noqa: BLE001 — qualquer falha de um provedor tenta o seguinte
            logger.warning('Provedor de IA %s falhou: %s', key, type(exc).__name__)
            last = exc
    raise LLMError('Todos os provedores de IA falharam agora. Tente de novo em instantes.') from last
