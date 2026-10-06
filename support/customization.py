"""Pedidos de parametrização (CAD-223). Fluxo:

recebido → em_analise → proposta (equipe Cadrius escreve o que fará, prazo e custo) → aprovado (dono/admin do escritório)
→ em_execucao → entregue. A equipe pode recusar explicando; o escritório pode cancelar antes da execução.
Nada que gere cobrança é executado sem a aprovação registrada do dono/admin (auditada).
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from accounts.team_roles import MANAGE_TEAM_ROLES
from audit import service as audit
from support import services
from support.models import CustomizationRequest, Ticket, TicketMessage

C = CustomizationRequest
STAFF_MOVES = {C.Stage.RECEIVED: {C.Stage.ANALYSIS, C.Stage.DECLINED}, C.Stage.ANALYSIS: {C.Stage.PROPOSAL, C.Stage.DECLINED},
               C.Stage.PROPOSAL: {C.Stage.ANALYSIS, C.Stage.DECLINED}, C.Stage.APPROVED: {C.Stage.IN_PROGRESS},
               C.Stage.IN_PROGRESS: {C.Stage.DELIVERED}}

# perguntas-guia por área (o front mostra como dica no formulário)
HINTS = {
    'automacao': 'Ex.: "Quando chegar publicação de sentença, criar tarefa de recurso para o advogado do processo e avisar o cliente."',
    'integracao': 'Diga o sistema (nome/site), o que deve ir e vir, e se ele tem API (o contato técnico deles ajuda).',
    'relatorio': 'Quais números, com que filtro (período, área, advogado) e quem vai ver.',
    'modelo': 'Anexe/cole um modelo atual e diga quais campos devem ser preenchidos sozinhos.',
    'acessos': 'Quem é a pessoa/função e o que ela pode ou não ver/alterar.',
    'financeiro': 'Regra de cobrança, régua, divisão de honorários entre advogados…',
    'fiscal': 'Regime tributário, prefeitura, código de serviço e o que precisa sair na nota.',
    'marketing': 'Canal, público e objetivo (sempre informativo — Provimento OAB 205/2021).',
    'importacao': 'De qual sistema/planilha, quantos registros e quais colunas.',
    'tribunais': 'Tribunal/comarca e qual rotina (pauta, suspensões, protocolo, certidões).',
    'outro': 'Descreva o resultado que você espera.',
}


def request_json(r: CustomizationRequest, staff=False) -> dict:
    return {'id': r.pk, 'chamado_id': r.ticket_id, 'area': r.area, 'area_label': r.get_area_display(), 'objetivo': r.objective,
            'exemplo': r.example, 'frequencia': r.frequency, 'pessoas': r.users_affected, 'desejado_para': r.wanted_by,
            'etapa': r.stage, 'etapa_label': r.get_stage_display(), 'proposta': r.proposal, 'prazo_dias': r.estimate_days,
            'custo_centavos': r.price_cents, 'aprovado_em': r.approved_at, 'entregue_em': r.delivered_at,
            'criado_em': r.created_at, 'atualizado_em': r.updated_at,
            **({'escritorio': str(r.ticket.organization)} if staff else {})}


def create(user, membership, data: dict) -> CustomizationRequest:
    area = data.get('area')
    if area not in C.Area.values:
        raise ValueError('Escolha a área do pedido.')
    objective = str(data.get('objetivo') or '').strip()
    if len(objective) < 20:
        raise ValueError('Descreva o que você precisa (mínimo 20 caracteres): o que deve acontecer e por quê.')
    wanted = None
    if data.get('desejado_para'):
        try:
            wanted = date.fromisoformat(str(data['desejado_para']))
        except ValueError as exc:
            raise ValueError('Data desejada no formato AAAA-MM-DD.') from exc
    try:
        people = max(1, min(int(data.get('pessoas') or 1), 500))
    except (TypeError, ValueError):
        people = 1
    title = str(data.get('titulo') or '').strip() or f'Parametrização: {C.Area(area).label}'
    with transaction.atomic():
        ticket = services.open_ticket(user, membership.organization, subject=title[:200], category=Ticket.Category.CUSTOMIZATION,
                                      priority=Ticket.Priority.NORMAL, body=objective, page_url=str(data.get('page_url') or ''))
        req = CustomizationRequest.objects.create(ticket=ticket, area=area, objective=objective[:5000],
                                                  example=str(data.get('exemplo') or '').strip()[:5000],
                                                  frequency=str(data.get('frequencia') or '').strip()[:40], users_affected=people,
                                                  wanted_by=wanted)
    audit.log('support.customization_requested', actor=user, organization=membership.organization, target=req, changes={'area': area})
    return req


def staff_update(user, req: CustomizationRequest, data: dict) -> CustomizationRequest:
    new = data.get('etapa', req.stage)
    if new != req.stage and new not in STAFF_MOVES.get(req.stage, set()):
        raise ValueError(f'De "{req.get_stage_display()}" não dá para ir para "{C.Stage(new).label if new in C.Stage.values else new}".')
    if new == C.Stage.PROPOSAL:
        proposal = str(data.get('proposta', req.proposal) or '').strip()
        if len(proposal) < 20:
            raise ValueError('Escreva a proposta: o que será feito, como e o prazo.')
        req.proposal = proposal[:5000]
        try:
            req.estimate_days = int(data['prazo_dias']) if data.get('prazo_dias') not in (None, '') else req.estimate_days
            req.price_cents = int(data['custo_centavos']) if data.get('custo_centavos') not in (None, '') else None
        except (TypeError, ValueError) as exc:
            raise ValueError('Prazo e custo precisam ser números.') from exc
    if new == C.Stage.DECLINED and len(str(data.get('motivo') or '').strip()) < 10:
        raise ValueError('Explique ao escritório por que não será feito (mínimo 10 caracteres).')
    before = req.stage
    req.stage = new
    if new == C.Stage.DELIVERED:
        req.delivered_at = timezone.now()
    req.save()
    note = {C.Stage.PROPOSAL: f'Proposta enviada:\n{req.proposal}', C.Stage.DECLINED: f'Pedido não será feito: {data.get("motivo")}',
            C.Stage.DELIVERED: 'Parametrização entregue. Confira e responda aqui se algo precisar de ajuste.'}.get(new)
    if note and new != before:
        services.staff_reply(user, req.ticket, note)
    if new == C.Stage.PROPOSAL and new != before:
        Ticket.objects.filter(pk=req.ticket_id).update(status=Ticket.Status.WAITING_CLIENT)
    audit.log('support.customization_updated', actor=user, organization=req.ticket.organization, target=req,
              changes={'de': before, 'para': new, 'custo_centavos': req.price_cents})
    return req


def client_decide(user, membership, req: CustomizationRequest, decision: str) -> CustomizationRequest:
    """Aprovar a proposta (só dono/admin: pode gerar custo) ou cancelar o pedido."""
    if decision == 'aprovar':
        if membership.role not in MANAGE_TEAM_ROLES:
            raise PermissionError('Só o dono ou administrador aprova a proposta.')
        if req.stage != C.Stage.PROPOSAL:
            raise ValueError('Não há proposta aguardando aprovação.')
        req.stage, req.approved_by, req.approved_at = C.Stage.APPROVED, user, timezone.now()
        TicketMessage.objects.create(ticket=req.ticket, author=user, body='Proposta aprovada pelo escritório.')
    elif decision == 'cancelar':
        if req.stage in (C.Stage.IN_PROGRESS, C.Stage.DELIVERED, C.Stage.DECLINED, C.Stage.CANCELED):
            raise ValueError('Este pedido não pode mais ser cancelado.')
        if membership.role not in MANAGE_TEAM_ROLES and req.ticket.opened_by_id != user.pk:
            raise PermissionError('Só quem pediu, o dono ou o administrador cancelam.')
        req.stage = C.Stage.CANCELED
    else:
        raise ValueError('Decisão: aprovar ou cancelar.')
    req.save()
    audit.log('support.customization_updated', actor=user, organization=membership.organization, target=req,
              changes={'decisao': decision, 'custo_centavos': req.price_cents})
    return req
