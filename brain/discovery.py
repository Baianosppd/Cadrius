"""Primeiro acesso guiado (CAD-226): "Fale sobre seu processo" → a IA indica automações.

O advogado conta, com as palavras dele, como o escritório trabalha (ou marca os temas que pesam no dia a dia). O Cadrius
devolve sugestões de automação em cima dos MODELOS PRONTOS (que já passaram por revisão) e, quando a pessoa cita uma
rotina semanal, uma regra semanal de tarefa. Tudo vira ``AutomationSuggestion`` (aceitar cria a regra DESLIGADA, como as
sugestões dos detectores), então não há caminho novo para ligar nada sem simulação.

Sem IA configurada (ou se ela falhar), as palavras-chave cobrem os temas: a entrevista nunca fica sem resposta.
O texto da pessoa não é guardado: só o motivo de cada sugestão (com no máximo um trecho curto) fica registrado.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata

from django.db import transaction

from brain.models import AutomationSuggestion

logger = logging.getLogger(__name__)

KEY_PREFIX = 'entrevista:'
MAX_TEXT = 4000
MAX_SUGGESTIONS = 6
S = AutomationSuggestion.Status

# Temas da entrevista (os mesmos botões da tela) → modelos prontos que resolvem cada um
TOPICS = {
    'prazos': ('Prazos e publicações', ['publicacao_prazo_fatal', 'prazo_lembrete', 'documento_prazo_fatal', 'suspensao_prazos_equipe']),
    'andamentos': ('Andamentos dos processos', ['andamento_cria_tarefa', 'andamento_avisa_cliente', 'processo_parado']),
    'clientes': ('Atendimento ao cliente', ['cliente_boas_vindas', 'email_cliente_responder', 'agenda_audiencia_cliente',
                                            'aniversario_cliente', 'detrator_ligar']),
    'emails': ('Caixa de e-mail', ['email_intimacao_tarefa', 'email_cliente_responder', 'email_comercial_aviso']),
    'agenda': ('Audiências e agenda', ['agenda_audiencia_cliente', 'agenda_prazo_equipe']),
    'cobranca': ('Honorários e cobrança', ['regua_lembrete', 'regua_vencido', 'pagamento_agradecimento', 'nota_enviar_cliente',
                                           'custas_reembolso']),
    'captacao': ('Captação de clientes', ['lead_responder', 'funil_reuniao_confirmacao', 'funil_parado', 'contrato_boas_vindas',
                                          'email_comercial_aviso']),
    'equipe': ('Organização da equipe', ['tarefa_atrasada_aviso', 'semanal_revisao', 'meta_mes_equipe']),
}

# Palavras do texto livre → tema (sem acento, minúsculas)
KEYWORDS = {
    'prazos': ['prazo', 'publicac', 'intimac', 'djen', 'diario oficial', 'fatal', 'perder prazo', 'contestac', 'recurso'],
    'andamentos': ['andamento', 'movimentac', 'processo parado', 'acompanh', 'cartorio', 'pje', 'esaj', 'tribunal'],
    'clientes': ['cliente', 'atendimento', 'retorno', 'duvida', 'ligac', 'whatsapp', 'satisfac', 'aniversario'],
    'emails': ['e-mail', 'email', 'caixa de entrada', 'gmail', 'outlook'],
    'agenda': ['audiencia', 'agenda', 'pericia', 'reuniao', 'compromisso', 'calendario'],
    'cobranca': ['honorario', 'cobranc', 'boleto', 'pagamento', 'inadimpl', 'nota fiscal', 'financeiro', 'custas', 'atraso no pagamento'],
    'captacao': ['captac', 'lead', 'indicac', 'novo cliente', 'site', 'instagram', 'proposta', 'contrato', 'funil', 'consulta'],
    'equipe': ['equipe', 'estagiario', 'associado', 'tarefa', 'reuniao semanal', 'meta', 'produtividade', 'organiz', 'atrasad'],
}

WEEKDAYS = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']


def _plain(text: str) -> str:
    t = unicodedata.normalize('NFKD', (text or '').lower())
    return ''.join(ch for ch in t if not unicodedata.combining(ch))


def topics_from_text(text: str) -> list[str]:
    """Temas citados no texto, do mais citado para o menos citado."""
    plain = _plain(text)
    hits = {k: sum(plain.count(w) for w in words) for k, words in KEYWORDS.items()}
    return [k for k, n in sorted(hits.items(), key=lambda kv: -kv[1]) if n > 0]


def _has_rule_from(org, template_key: str) -> bool:
    from automations.models import Rule
    return Rule.objects.filter(organization=org, template_key=template_key).exists()


def _snippet(text: str, words: list[str]) -> str:
    """Trecho curto (até 90 caracteres) da frase em que o tema aparece — para o motivo fazer sentido para quem falou."""
    for sentence in re.split(r'(?<=[.!?\n])\s+', text or ''):
        if any(w in _plain(sentence) for w in words):
            s = sentence.strip()
            return s if len(s) <= 90 else s[:87].rstrip() + '…'
    return ''


# ----------------------------------------------------------------------------- IA (opcional)
SYSTEM = (
    'Você ajuda um escritório de advocacia brasileiro a escolher automações. Leia como o advogado descreve o trabalho e '
    'escolha, na lista de MODELOS, os que mais aliviam a rotina descrita (no máximo 5, do mais útil ao menos útil). '
    'Se ele citar uma tarefa que se repete toda semana, inclua em "semanais" (no máximo 2). '
    'Responda só JSON: {"modelos":[{"chave":"<chave da lista>","motivo":"<1 frase em português, citando o que ele disse>"}],'
    '"semanais":[{"titulo":"<tarefa>","dia_semana":0-6 (0 = segunda),"hora":6-20,"motivo":"<1 frase>"}]}. '
    'Nunca invente chave fora da lista.'
)


def _ask_ai(org, user, text: str, topics: list[str]):
    """Pede à IA a escolha dos modelos. Devolve dict ou None (sem IA, bloqueada, sem crédito ou resposta inválida)."""
    from aigov import llm
    from aigov.guard import AIBlocked, get_policy, global_ai_enabled, run_guarded
    from automations.templates import TEMPLATES
    from billing.credits import charge

    if not global_ai_enabled():
        return None
    providers = llm.candidates(get_policy(org).allowed_providers, sensitive=True, profile='automacao', org=org)
    if not providers:
        return None
    ok, _ = charge(org, 'automation_draft', user_id=getattr(user, 'pk', None))
    if not ok:
        return None
    catalog = '\n'.join(f'- {k}: {t["name"]}. {t["description"]}' for k, t in TEMPLATES.items())
    prompt = f'MODELOS:\n{catalog}\n\nTEMAS MARCADOS: {", ".join(topics) or "nenhum"}\n\nCOMO O ESCRITÓRIO TRABALHA:\n{text}'
    try:
        reply = run_guarded(organization=org, user=user, kind='assistant', provider=providers[0], categories=['operacional'],
                            input_text=text, fn=lambda: llm.chat_with_fallback(
                                providers, system=SYSTEM, messages=[{'role': 'user', 'content': prompt}],
                                json_mode=True, max_tokens=1200, org=org))
    except AIBlocked:
        return None
    except Exception as exc:  # noqa: BLE001 — sem IA, as palavras-chave respondem
        logger.warning('Entrevista de automações sem IA: %s', type(exc).__name__)
        return None
    raw = (reply.text or '').strip()
    raw = raw[raw.find('{'):raw.rfind('}') + 1] if '{' in raw else ''
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _weekly_rule(item: dict):
    title = str(item.get('titulo') or '').strip()[:120]
    try:
        day, hour = int(item.get('dia_semana', 0)), int(item.get('hora', 9))
    except (TypeError, ValueError):
        return None
    if len(title) < 4 or not 0 <= day <= 6:
        return None
    return {'name': f'Toda {WEEKDAYS[day]}: {title}'[:120], 'trigger': 'schedule',
            'trigger_config': {'frequencia': 'semanal', 'dia_semana': day, 'hora': max(6, min(hour, 20)), 'so_dias_uteis': True},
            'conditions': [], 'actions': [{'type': 'create_task', 'params': {
                'titulo': title, 'descricao': 'Criada pela regra semanal (entrevista do primeiro acesso).', 'prioridade': 'media',
                'quando': 'dias_uteis', 'dias': 0}}]}


# ----------------------------------------------------------------------------- entrada
def discover(org, user, text: str = '', topics=None) -> dict:
    """Gera (ou atualiza) as sugestões da entrevista. Devolve {'origem': 'ia'|'temas', 'temas': [...], 'sugestoes': [AutomationSuggestion]}."""
    from automations import catalog
    from automations.templates import TEMPLATES

    text = (text or '').strip()[:MAX_TEXT]
    chosen = [t for t in (topics or []) if t in TOPICS]
    found_topics = list(dict.fromkeys(chosen + topics_from_text(text)))

    picks: list[tuple[str, str, str, dict]] = []      # (key, title, reason, payload)
    origin = 'temas'
    ai = _ask_ai(org, user, text, found_topics) if len(text) >= 20 else None
    if ai:
        origin = 'ia'
        for item in (ai.get('modelos') or [])[:5]:
            key = str((item or {}).get('chave', ''))
            if key in TEMPLATES:
                reason = str(item.get('motivo') or '').strip()[:300] or TEMPLATES[key]['description']
                picks.append((f'{KEY_PREFIX}{key}', TEMPLATES[key]['name'], reason, {'template': key}))
        for item in (ai.get('semanais') or [])[:2]:
            rule = _weekly_rule(item or {})
            if rule is None:
                continue
            try:
                catalog.clean_rule(rule)
            except catalog.RuleError:
                continue
            digest = hashlib.sha256(_plain(rule['name']).encode()).hexdigest()[:10]
            picks.append((f'{KEY_PREFIX}semanal:{digest}', rule['name'][:160],
                          str(item.get('motivo') or 'Você contou que faz isso toda semana.')[:300], {'rule': rule}))

    # Temas (marcados ou citados) completam a lista — e respondem sozinhos quando não há IA
    for topic in found_topics:
        label, keys = TOPICS[topic]
        quote = _snippet(text, KEYWORDS[topic])
        for key in keys:
            if any(p[3].get('template') == key for p in picks):
                continue
            reason = (f'Você comentou: "{quote}". ' if quote else f'Você marcou "{label}". ') + TEMPLATES[key]['description']
            picks.append((f'{KEY_PREFIX}{key}', TEMPLATES[key]['name'], reason, {'template': key}))
            break                                          # um modelo por tema na primeira leva: lista curta, decisão fácil

    out = []
    with transaction.atomic():
        for key, title, reason, payload in picks:
            if len(out) >= MAX_SUGGESTIONS:
                break
            if payload.get('template') and _has_rule_from(org, payload['template']):
                continue
            s = AutomationSuggestion.objects.filter(organization=org, key=key[:80]).first()
            if s is None:
                s = AutomationSuggestion.objects.create(organization=org, key=key[:80], title=title[:160], reason=reason,
                                                        evidence=0, payload=payload)
            elif s.status == S.OPEN:
                s.title, s.reason, s.payload = title[:160], reason, payload
                s.save()
            else:
                continue                                   # já aceita ou dispensada: não insiste
            out.append(s)

    from audit import service as audit
    audit.log('automation.discovery', actor=user, organization=org,
              changes={'origem': origin, 'temas': found_topics, 'sugestoes': len(out), 'texto_chars': len(text)})
    return {'origem': origin, 'temas': found_topics, 'sugestoes': out}
