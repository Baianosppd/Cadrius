"""Matriz de autonomia (CAD-165): quanto a IA pode fazer SOZINHA, por tipo de ação e por escritório.

Classes de risco (docs/PLANO_EVOLUCAO_PRODUTO.md §8.2):
  R1 rascunho interno · R2 ação interna reversível · R3 efeito externo reversível · R4 irreversível/alto impacto.
**R4 nunca é automático** (protocolar peça, prazo fatal, pagamento, exclusão): só ``off`` ou ``review``, sem opção de mudar.
A promoção de nível é **sugerida** por critérios objetivos (volume + taxa de aprovação sem edição + zero desfazimentos) e **decidida pelo sócio**;
qualquer erro grave rebaixa na hora para ``review``.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from audit import service as audit
from brain.models import AIFeedback, AutonomyLevel, AutonomyProposal

MODES = ('off', 'review', 'auto_undo', 'auto')

# action_kind -> rótulo, risco, modo padrão e modos permitidos (em ordem crescente de autonomia)
ACTION_KINDS = {
    'document_extraction': {'label': 'Leitura de documentos', 'risk': 'R1', 'default': 'review', 'allowed': ('off', 'review', 'auto')},
    'deadline_task': {'label': 'Criar tarefas dos prazos lidos', 'risk': 'R2', 'default': 'review', 'allowed': ('off', 'review', 'auto_undo')},
    'client_message': {'label': 'Mensagens ao cliente', 'risk': 'R3', 'default': 'review', 'allowed': ('off', 'review')},
    'petition_filing': {'label': 'Protocolar peças', 'risk': 'R4', 'default': 'review', 'allowed': ('off', 'review')},
    'fatal_deadline': {'label': 'Definir/alterar prazo fatal', 'risk': 'R4', 'default': 'review', 'allowed': ('off', 'review')},
    'payment': {'label': 'Honorários e pagamentos', 'risk': 'R4', 'default': 'review', 'allowed': ('off', 'review')},
    'data_deletion': {'label': 'Excluir dados', 'risk': 'R4', 'default': 'review', 'allowed': ('off', 'review')},
}

PROMO_MIN_SAMPLES = 30
PROMO_MIN_RATE = Decimal('0.95')
PROMO_WINDOW_DAYS = 60


class AutonomyError(ValueError):
    pass


def resolve(organization, kind) -> str:
    spec = ACTION_KINDS[kind]
    row = AutonomyLevel.objects.filter(organization=organization, action_kind=kind).values_list('mode', flat=True).first()
    return row if row in spec['allowed'] else spec['default']


def is_auto(organization, kind) -> bool:
    return resolve(organization, kind) in ('auto', 'auto_undo')


def set_level(organization, kind, mode, user=None):
    spec = ACTION_KINDS.get(kind)
    if spec is None:
        raise AutonomyError('Tipo de ação desconhecido.')
    if mode not in spec['allowed']:
        if spec['risk'] == 'R4':
            raise AutonomyError('Ações de alto impacto (R4) sempre exigem a decisão do advogado: não podem ser automáticas.')
        raise AutonomyError(f'Modo "{mode}" não é permitido para esta ação. Permitidos: {", ".join(spec["allowed"])}.')
    old = resolve(organization, kind)
    AutonomyLevel.objects.update_or_create(organization=organization, action_kind=kind, defaults={'mode': mode, 'updated_by': user})
    audit.log('ai.autonomy_changed', actor=user, organization=organization,
              changes={'action_kind': kind, 'from': old, 'to': mode, 'risk': spec['risk']})
    return mode


def stats(organization, kind, now=None):
    since = (now or timezone.now()) - timedelta(days=PROMO_WINDOW_DAYS)
    rows = dict(AIFeedback.objects.filter(organization=organization, action_kind=kind, created_at__gte=since)
                .values_list('decision').annotate(n=Count('id')))
    total = sum(rows.values())
    approved = rows.get('approved', 0)
    return {'samples': total, 'approved': approved, 'edited': rows.get('edited', 0), 'rejected': rows.get('rejected', 0),
            'undone': rows.get('undone', 0),
            'approval_rate': round(Decimal(approved) / Decimal(total), 2) if total else Decimal('0')}


def evaluate_promotions(organization, now=None):
    """Cria SUGESTÕES de promoção para ações que atingiram os critérios. Não muda nada sozinho."""
    created = []
    for kind, spec in ACTION_KINDS.items():
        if spec['risk'] == 'R4':
            continue
        modes = spec['allowed']
        current = resolve(organization, kind)
        if current == 'off' or current not in modes or modes.index(current) == len(modes) - 1:
            continue
        s = stats(organization, kind, now)
        if s['samples'] < PROMO_MIN_SAMPLES or s['approval_rate'] < PROMO_MIN_RATE or s['undone'] or s['rejected']:
            continue
        if AutonomyProposal.objects.filter(organization=organization, action_kind=kind, status='open').exists():
            continue
        created.append(AutonomyProposal.objects.create(
            organization=organization, action_kind=kind, from_mode=current, to_mode=modes[modes.index(current) + 1],
            samples=s['samples'], approval_rate=s['approval_rate']))
    return created


def decide_proposal(proposal, user, approve: bool):
    if proposal.status != AutonomyProposal.Status.OPEN:
        raise AutonomyError('Esta sugestão já foi decidida.')
    proposal.status = AutonomyProposal.Status.APPROVED if approve else AutonomyProposal.Status.REJECTED
    proposal.decided_by, proposal.decided_at = user, timezone.now()
    proposal.save()
    if approve:
        set_level(proposal.organization, proposal.action_kind, proposal.to_mode, user)
    return proposal


def report_error(organization, kind, reason='', user=None):
    """Erro grave numa ação automática: volta para ``review`` na hora e avisa na trilha. Recomeça a contar a confiança."""
    if resolve(organization, kind) in ('auto', 'auto_undo'):
        AutonomyLevel.objects.update_or_create(organization=organization, action_kind=kind,
                                               defaults={'mode': ACTION_KINDS[kind]['default'], 'updated_by': user})
        audit.log('ai.autonomy_changed', actor=user, organization=organization, outcome='error', reason=f'rebaixada: {reason}'[:200],
                  changes={'action_kind': kind, 'to': ACTION_KINDS[kind]['default']})
        return True
    return False
