"""Triagem das publicações (CAD-173): qual é o ato, qual prazo provável, o que fazer. É SUGESTÃO — quem confirma é o advogado.

1. Leitura local (sempre): palavras-chave do ato e "prazo de N (N) dias" no texto. Sem prazo escrito, usa o prazo legal mais comum
   para o ato (CPC) e marca a confiança como baixa.
2. IA (se a política do escritório permitir e houver provedor): confere/complementa a leitura local, com o texto mascarado.
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

NUMBERS = {'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'três': 3, 'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6, 'sete': 7, 'oito': 8,
           'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12, 'treze': 13, 'quatorze': 14, 'catorze': 14, 'quinze': 15, 'vinte': 20,
           'trinta': 30, 'quarenta': 40, 'sessenta': 60, 'noventa': 90}
_WORDS = '|'.join(sorted(NUMBERS, key=len, reverse=True))
PRAZO_RX = re.compile(rf'prazo\s+(?:comum\s+|sucessivo\s+|legal\s+|improrrog[aá]vel\s+)?de\s+(?:(\d{{1,3}})|({_WORDS}))'
                      rf'(?:\s*\(\s*(?:\d{{1,3}}|[a-zç ]+)\s*\))?\s+dias', re.IGNORECASE)
AUDIENCIA_RX = re.compile(r'audi[eê]ncia[^.\n]{0,120}?(\d{2}/\d{2}/\d{4})(?:[^.\n]{0,20}?(\d{1,2}[:h]\d{2}))?', re.IGNORECASE)

# (rótulo, padrões, prazo legal típico em dias úteis, providência sugerida, fatal?)
ACTS = [
    ('Citação', r'\bcita[çc][aã]o\b|\bcite-se\b', 15, 'Contestar (CPC art. 335) ou avaliar acordo.', True),
    ('Sentença', r'\bsenten[çc]a\b|julgo\s+(?:procedente|improcedente|parcialmente)', 15, 'Avaliar recurso: apelação em 15 dias úteis '
     '(CPC art. 1.003 §5º) ou embargos de declaração em 5 dias (art. 1.023).', True),
    ('Acórdão', r'\bac[óo]rd[ãa]o\b|acordam\s+os', 15, 'Avaliar recursos (especial/extraordinário em 15 dias) ou embargos em 5 dias.', True),
    ('Audiência', r'\baudi[eê]ncia\b', None, 'Agendar a audiência e avisar o cliente e as testemunhas.', False),
    ('Decisão', r'\bdecis[ãa]o\b|\bdefiro\b|\bindefiro\b|tutela', 15, 'Avaliar agravo de instrumento (15 dias, CPC art. 1.015) '
     'ou cumprimento.', False),
    ('Despacho', r'\bdespacho\b|\bintime-se\b|manifeste-se|\bvista\b', 5, 'Cumprir/manifestar-se no prazo do despacho.', False),
    ('Edital', r'\bedital\b', None, 'Conferir o edital e o prazo nele indicado.', False),
]
DEFAULT_DAYS = 5         # CPC art. 218 §3º: sem prazo fixado, 5 dias


def _days_from_text(text: str):
    m = PRAZO_RX.search(text or '')
    if not m:
        return None
    n = int(m.group(1)) if m.group(1) else NUMBERS.get(m.group(2).lower())
    return n if n and 1 <= n <= 365 else None


def local_triage(text: str, tipo: str = '') -> dict:
    body = f'{tipo}\n{text or ""}'
    ato, typical, providencia, fatal = 'Intimação', DEFAULT_DAYS, 'Ler a íntegra e definir a providência.', False
    for label, rx, days, todo, is_fatal in ACTS:
        if re.search(rx, body, re.IGNORECASE):
            ato, typical, providencia, fatal = label, days, todo, is_fatal
            break
    written = _days_from_text(text)
    out = {'ato': ato, 'providencia': providencia, 'origem': 'local', 'fatal': bool(fatal)}
    if written:
        out.update(prazo_dias=written, prazo_origem='texto', confianca=80)
    elif typical:
        out.update(prazo_dias=typical, prazo_origem='prazo legal típico (confira)', confianca=45)
    else:
        out.update(prazo_dias=None, prazo_origem='', confianca=40)
    aud = AUDIENCIA_RX.search(text or '')
    if aud:
        out['audiencia'] = f'{aud.group(1)} {aud.group(2).replace("h", ":")}' if aud.group(2) else aud.group(1)
    first = re.sub(r'\s+', ' ', text or '').strip()
    out['resumo'] = (first[:280] + '…') if len(first) > 280 else first
    return out


class TriageSchema(BaseModel):
    ato: str = Field(description='Tipo do ato: Intimação, Citação, Sentença, Acórdão, Decisão, Despacho, Audiência ou Edital')
    prazo_dias: int | None = Field(default=None, description='Prazo em dias úteis para a providência; null se não houver')
    prazo_justificativa: str = Field(default='', description='Trecho do texto ou dispositivo legal que fundamenta o prazo')
    fatal: bool = Field(default=False, description='true se perder o prazo causa preclusão/perda do direito')
    providencia: str = Field(default='', description='O que o advogado deve fazer, em uma frase')
    resumo: str = Field(default='', description='Resumo em até 2 frases, em português simples')
    audiencia: str | None = Field(default=None, description='Data e hora da audiência (DD/MM/AAAA HH:MM), se houver')


PROMPT = ('Você faz a triagem de uma publicação do Diário de Justiça para um escritório de advocacia. Identifique o ato, o prazo '
          'em dias úteis e a providência. Use o prazo escrito no texto quando houver; se não houver, o prazo legal do CPC e diga '
          'qual na justificativa. Não invente fatos.')


def ai_triage(organization, user, text: str):
    """Triagem pela IA (ou None se não der: política, provedor, falha). Nunca levanta."""
    from aigov.guard import AIBlocked, get_policy, run_guarded
    from core.pii import mask_text
    from documents.pipeline import Skip, fallbacks_for, pick_provider
    from extraction.ai_wrapper import extract_fields_from_text

    masked = mask_text(text)[:12000]
    try:
        # publicação traz prazo: usa a cadeia de EXTRAÇÃO (precisão), não a de triagem rápida (CAD-224)
        provider = pick_provider(get_policy(organization), activity='extracao')
        reserves = fallbacks_for(get_policy(organization), provider, activity='extracao')
        result = run_guarded(organization=organization, user=user, kind='triage', provider=provider,
                             categories=['dados_processuais'], input_text=masked,
                             fn=lambda: extract_fields_from_text(masked, TriageSchema, PROMPT, provider=provider, fallbacks=reserves))
    except (Skip, AIBlocked):
        return None
    except Exception:  # noqa: BLE001 — triagem pela IA é um extra; a leitura local já existe
        logger.exception('Falha na triagem por IA')
        return None
    if result:
        from billing.credits import charge
        charge(organization, 'triage', user_id=getattr(user, 'pk', None))      # CAD-225
    return {**result, 'origem': provider} if result else None


def triage(organization, text: str, tipo: str = '', user=None) -> dict:
    local = local_triage(text, tipo)
    ai = ai_triage(organization, user, text)
    if not ai:
        return local
    merged = {**local, **{k: v for k, v in ai.items() if v not in (None, '')}}
    if ai.get('prazo_dias'):
        merged['prazo_origem'] = ai.get('prazo_justificativa') or 'IA'
    merged['confianca'] = 85 if ai.get('prazo_dias') == local.get('prazo_dias') else 65
    merged.pop('prazo_justificativa', None)
    return merged
