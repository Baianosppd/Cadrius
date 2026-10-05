"""Feedback das decisões humanas, regras aprendidas (propostas) e sua aplicação (CAD-165)."""
from __future__ import annotations

from collections import Counter

from django.utils import timezone

from audit import service as audit
from brain import style
from brain.models import AIFeedback, OfficeRule

RULE_FIELDS = ('tipo_documento',)        # campos de valor "pequeno" em que uma correção repetida vira regra
MIN_EVIDENCE = 5


def diff_fields(original: dict, final: dict) -> list:
    """Lista de mudanças entre a leitura da IA e a versão revisada. Escalares: de→para; listas: só a contagem/valores."""
    changes = []
    for key in sorted(set(original) | set(final)):
        if key.startswith('_'):
            continue
        a, b = original.get(key), final.get(key)
        if a == b:
            continue
        if isinstance(a, list) or isinstance(b, list):
            changes.append({'field': key, 'from': len(a or []), 'to': len(b or []), 'kind': 'list'})
        else:
            changes.append({'field': key, 'from': '' if a is None else str(a)[:120], 'to': '' if b is None else str(b)[:120]})
    return changes


def record_review(organization, user, action_kind, subject, original: dict, final: dict, confidence=None) -> AIFeedback:
    changes = diff_fields(original or {}, final or {})
    if action_kind in style.KINDS and isinstance((original or {}).get('texto'), str) and isinstance((final or {}).get('texto'), str):
        changes += style.term_changes(original['texto'], final['texto'])      # vocabulário do escritório (CAD-174)
    return AIFeedback.objects.create(
        organization=organization, user=user, action_kind=action_kind, subject=subject,
        decision=AIFeedback.Decision.EDITED if changes else AIFeedback.Decision.APPROVED, changes=changes, confidence=confidence)


def record_decision(organization, user, action_kind, subject, decision, confidence=None) -> AIFeedback:
    return AIFeedback.objects.create(organization=organization, user=user, action_kind=action_kind, subject=subject,
                                     decision=decision, confidence=confidence)


def mine_rules(organization, min_evidence=MIN_EVIDENCE):
    """Procura correções repetidas (campo A→B) e PROPÕE regras. Nada vale até um advogado aprovar."""
    counts = Counter()
    for fb in AIFeedback.objects.filter(organization=organization, action_kind='document_extraction', decision='edited').iterator():
        for ch in fb.changes or []:
            if ch.get('field') in RULE_FIELDS and ch.get('kind') != 'list' and ch.get('from') and ch.get('to'):
                counts[(ch['field'], ch['from'], ch['to'])] += 1
    created = []
    for (field, frm, to), n in counts.items():
        if n < min_evidence:
            continue
        rule, was_created = OfficeRule.objects.get_or_create(organization=organization, kind='field_correction', field=field,
                                                              from_value=frm, to_value=to, defaults={'evidence': n})
        if was_created:
            created.append(rule)
        elif rule.status == OfficeRule.Status.PROPOSED and rule.evidence != n:
            rule.evidence = n
            rule.save(update_fields=['evidence'])
    return created


def apply_rules(organization, fields: dict):
    """Aplica as regras ATIVAS do escritório sobre a leitura. Devolve (campos, [descrições aplicadas])."""
    applied = []
    out = dict(fields)
    for rule in OfficeRule.objects.filter(organization=organization, status=OfficeRule.Status.ACTIVE, kind='field_correction'):
        if str(out.get(rule.field, '')) == rule.from_value:
            out[rule.field] = rule.to_value
            applied.append(rule.describe())
    return out, applied


def decide_rule(rule: OfficeRule, user, decision: str) -> OfficeRule:
    mapping = {'approve': OfficeRule.Status.ACTIVE, 'reject': OfficeRule.Status.REJECTED, 'disable': OfficeRule.Status.DISABLED}
    if decision not in mapping:
        raise ValueError('decision deve ser approve, reject ou disable.')
    if decision == 'approve' and rule.status not in (OfficeRule.Status.PROPOSED, OfficeRule.Status.DISABLED):
        raise ValueError('Só propostas ou regras desligadas podem ser aprovadas.')
    rule.status, rule.decided_by, rule.decided_at = mapping[decision], user, timezone.now()
    rule.save()
    audit.log('ai.rule_decided', actor=user, organization=rule.organization, target=rule,
              changes={'decision': decision, 'field': rule.field, 'from': rule.from_value, 'to': rule.to_value})
    return rule
