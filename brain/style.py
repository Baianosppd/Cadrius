"""Vocabulário do escritório (CAD-174): aprende as trocas de termos que a equipe faz nos textos gerados pela IA.

Quando uma minuta ou um conteúdo de marketing é revisado, comparamos o texto gerado com o final palavra a palavra.
Trocas curtas de termos comuns ("requerente" → "autor", "cliente" → "constituinte") viram sinais; a mesma troca em
textos diferentes vira uma PROPOSTA de regra (OfficeRule kind='term'). Só depois que um advogado aprova ela passa a:
1) entrar no prompt da IA e 2) ser aplicada no texto gerado. Nomes próprios, números e dados pessoais nunca viram regra.
"""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from brain.models import AIFeedback, OfficeRule

KINDS = ('draft', 'marketing')
MIN_EVIDENCE = 3            # a mesma troca em pelo menos 3 textos diferentes
MAX_SPAN = 4                # trocas de até 4 palavras de cada lado
MAX_TERMS_PER_TEXT = 40
# Palavras com inicial maiúscula normalmente são nomes (partes, cidades): só aceitamos as formas de tratamento.
TITLE_WORDS = {'vossa', 'excelência', 'excelentíssimo', 'excelentíssima', 'meritíssimo', 'meritíssima', 'senhor', 'senhora', 'senhoria',
               'doutor', 'doutora', 'juízo', 'juiz', 'juíza', 'egrégio', 'egrégia', 'colendo', 'colenda', 'douto', 'douta'}
_TOKEN = re.compile(r"[A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)*|\d+")       # pontuação não conta como troca
_WORD = re.compile(r'^[a-zà-ÿ]+(?:-[a-zà-ÿ]+)*$')


def _tokens(text: str) -> list:
    return _TOKEN.findall(text or '')


def _ok_span(tokens: list) -> bool:
    if not 1 <= len(tokens) <= MAX_SPAN:
        return False
    for t in tokens:
        if not _WORD.match(t) and t.lower() not in TITLE_WORDS:
            return False                        # número, pontuação, nome próprio
    return any(len(t) >= 4 for t in tokens)


def term_changes(original: str, final: str) -> list:
    """Trocas de termos entre o texto gerado e o revisado: [{'field': 'termo', 'from': 'requerente', 'to': 'autor', 'kind': 'term'}]."""
    a, b = _tokens(original), _tokens(final)
    if not a or not b:
        return []
    seen, out = set(), []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, [t.lower() for t in a], [t.lower() for t in b], autojunk=False).get_opcodes():
        if op != 'replace':
            continue
        src, dst = a[i1:i2], b[j1:j2]
        if not (_ok_span(src) and _ok_span(dst)):
            continue
        frm, to = ' '.join(src).lower(), ' '.join(dst).lower()
        if frm == to or (frm, to) in seen:
            continue
        seen.add((frm, to))
        out.append({'field': 'termo', 'from': frm[:120], 'to': to[:120], 'kind': 'term'})
        if len(out) >= MAX_TERMS_PER_TEXT:
            break
    return out


def mine_terms(organization, min_evidence=MIN_EVIDENCE) -> list:
    """Propõe regras de vocabulário a partir de trocas repetidas em textos diferentes. Nada vale sem aprovação."""
    subjects = defaultdict(set)
    qs = AIFeedback.objects.filter(organization=organization, action_kind__in=KINDS, decision='edited').order_by('-created_at')[:500]
    for fb in qs:
        for ch in fb.changes or []:
            if ch.get('kind') == 'term' and ch.get('from') and ch.get('to'):
                subjects[(ch['from'], ch['to'])].add(fb.subject or fb.pk)
    created = []
    for (frm, to), subj in subjects.items():
        n = len(subj)
        if n < min_evidence:
            continue
        rule, was_created = OfficeRule.objects.get_or_create(organization=organization, kind='term', field='texto',
                                                              from_value=frm, to_value=to, defaults={'evidence': n})
        if was_created:
            created.append(rule)
        elif rule.status == OfficeRule.Status.PROPOSED and rule.evidence != n:
            rule.evidence = n
            rule.save(update_fields=['evidence'])
    return created


def active_terms(organization) -> list:
    if organization is None:
        return []
    return list(OfficeRule.objects.filter(organization=organization, kind='term', status=OfficeRule.Status.ACTIVE)
                .order_by('-evidence').values_list('from_value', 'to_value')[:50])


def _match_case(src: str, dst: str) -> str:
    if src.isupper() and len(src) > 1:
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def apply_terms(organization, text: str) -> tuple[str, int]:
    """Aplica o vocabulário ATIVO do escritório (palavra inteira, sem diferenciar maiúsculas). Devolve (texto, nº de trocas)."""
    total = 0
    for frm, to in active_terms(organization):
        pattern = re.compile(r'(?<![\wÀ-ÿ])' + r'\s+'.join(re.escape(w) for w in frm.split()) + r'(?![\wÀ-ÿ])', re.IGNORECASE)
        text, n = pattern.subn(lambda m, to=to: _match_case(m.group(0), to), text or '')
        total += n
    return text, total


def prompt_context(organization) -> str:
    terms = active_terms(organization)[:20]
    if not terms:
        return ''
    return ('\n\nVocabulário do escritório (aprovado pela equipe): '
            + '; '.join(f'escreva "{to}" em vez de "{frm}"' for frm, to in terms) + '.')
