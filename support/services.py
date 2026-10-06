"""Regras do suporte (CAD-171): quem vê o quê, transições de estado, avisos."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Avg, F
from django.utils import timezone

from accounts.team_roles import MANAGE_TEAM_ROLES
from audit import service as audit
from support.models import SupportAccessGrant, Ticket, TicketMessage

MAX_BODY = 5000
GRANT_HOURS = (24, 72)


def can_see(membership, ticket) -> bool:
    """Cliente: quem abriu vê o seu; dono/admin veem todos os do escritório."""
    return bool(membership and ticket.organization_id == membership.organization_id
                and (ticket.opened_by_id == membership.user_id or membership.role in MANAGE_TEAM_ROLES))


def ticket_json(t, *, staff=False) -> dict:
    grant = t.active_grant()
    data = {'id': t.pk, 'subject': t.subject, 'category': t.category, 'category_label': t.get_category_display(),
            'priority': t.priority, 'priority_label': t.get_priority_display(), 'status': t.status, 'status_label': t.get_status_display(),
            'page_url': t.page_url, 'created_at': t.created_at, 'updated_at': t.updated_at,
            'first_response_at': t.first_response_at, 'resolved_at': t.resolved_at,
            'opened_by': t.opened_by.email if t.opened_by_id else '',
            'access_until': grant.expires_at if grant else None,
            'parametrizacao': _customization(t)}
    if staff:
        data.update({'organization': str(t.organization), 'organization_id': str(t.organization_id),
                     'assigned_to': t.assigned_to.email if t.assigned_to_id else None})
    return data


def _customization(t):
    r = getattr(t, 'customization', None) if t.category == Ticket.Category.CUSTOMIZATION else None
    return {'id': r.pk, 'etapa': r.stage, 'etapa_label': r.get_stage_display(), 'area_label': r.get_area_display()} if r else None


def messages_json(t, *, staff=False) -> list[dict]:
    qs = t.messages.select_related('author')
    if not staff:
        qs = qs.filter(internal=False)
    return [{'id': m.pk, 'body': m.body, 'from_staff': m.from_staff, 'internal': m.internal,
             'author': (m.author.get_full_name() or m.author.email) if m.author_id and (staff or not m.from_staff) else
             ('Equipe Cadrius' if m.from_staff else ''), 'created_at': m.created_at} for m in qs]


def clean_body(text) -> str:
    text = str(text or '').strip()
    if len(text) < 5:
        raise ValueError('Escreva a mensagem (mínimo 5 caracteres).')
    return text[:MAX_BODY]


def open_ticket(user, organization, *, subject, category, priority, body, page_url):
    subject = str(subject or '').strip()[:200]
    if len(subject) < 5:
        raise ValueError('Informe o assunto (mínimo 5 caracteres).')
    body = clean_body(body)
    ticket = Ticket.objects.create(
        organization=organization, opened_by=user, subject=subject,
        category=category if category in Ticket.Category.values else Ticket.Category.QUESTION,
        priority=priority if priority in (Ticket.Priority.NORMAL, Ticket.Priority.HIGH) else Ticket.Priority.NORMAL,
        page_url=str(page_url or '')[:300])
    TicketMessage.objects.create(ticket=ticket, author=user, body=body)
    audit.log('support.ticket_opened', actor=user, organization=organization, target=ticket, changes={'category': ticket.category})
    _notify_staff(ticket)
    return ticket


def _notify_staff(ticket):
    to = getattr(settings, 'SUPPORT_NOTIFY_EMAIL', '')
    if not to:
        return
    try:
        send_mail(f'[Cadrius suporte] Novo chamado #{ticket.pk} ({ticket.get_priority_display()})',
                  f'Novo chamado de {ticket.organization}. Abra a Gestão Cadrius → Suporte para ver.\n'
                  '(O conteúdo não vai por e-mail: fica cifrado no sistema.)',
                  None, [to], fail_silently=True)
    except Exception:  # noqa: BLE001 — aviso por e-mail nunca impede o chamado
        pass


def client_reply(user, ticket, body):
    if ticket.status == Ticket.Status.CLOSED:
        raise ValueError('Chamado fechado. Reabra para continuar a conversa.')
    TicketMessage.objects.create(ticket=ticket, author=user, body=clean_body(body))
    ticket.status = Ticket.Status.OPEN if ticket.status in (Ticket.Status.WAITING_CLIENT, Ticket.Status.RESOLVED) else ticket.status
    ticket.save(update_fields=['status', 'updated_at'])


def staff_reply(user, ticket, body, internal=False):
    if ticket.status == Ticket.Status.CLOSED:
        raise ValueError('Chamado fechado.')
    TicketMessage.objects.create(ticket=ticket, author=user, body=clean_body(body), from_staff=True, internal=internal)
    fields = ['updated_at']
    if not internal:
        if ticket.first_response_at is None:
            ticket.first_response_at = timezone.now()
            fields.append('first_response_at')
        if ticket.status in (Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS):
            ticket.status = Ticket.Status.WAITING_CLIENT
            fields.append('status')
        _notify_client(ticket)
    if ticket.assigned_to_id is None:
        ticket.assigned_to = user
        fields.append('assigned_to')
    ticket.save(update_fields=fields)
    audit.log('support.staff_reply', actor=user, organization=ticket.organization, target=ticket, changes={'internal': internal})


def _notify_client(ticket):
    if not ticket.opened_by_id:
        return
    from notifications.models import Notification
    from notifications.services import notify
    notify(type=Notification.Type.SUPORTE, title='Resposta da equipe Cadrius', organization=ticket.organization,
           actor_id=ticket.opened_by_id, origem='Suporte', documento=f'Chamado #{ticket.pk}',
           description='A equipe respondeu ao seu chamado.', acao='Nova resposta', action_label='Ver chamado',
           link=f'/suporte?chamado={ticket.pk}', dedupe_key=f'suporte-{ticket.pk}-{timezone.now():%Y%m%d%H%M}')


def set_status(ticket, new_status):
    if new_status not in Ticket.Status.values:
        raise ValueError('Situação inválida.')
    ticket.status = new_status
    ticket.resolved_at = timezone.now() if new_status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED) else None
    ticket.save(update_fields=['status', 'resolved_at', 'updated_at'])


def grant_access(user, ticket, hours):
    if hours not in GRANT_HOURS:
        raise ValueError('Escolha 24 ou 72 horas.')
    grant = SupportAccessGrant.objects.create(ticket=ticket, granted_by=user, expires_at=timezone.now() + timedelta(hours=hours))
    audit.log('support.access_granted', actor=user, organization=ticket.organization, target=ticket,
              changes={'hours': hours}, legal_basis='consentimento')
    return grant


def revoke_access(user, ticket):
    n = ticket.access_grants.filter(revoked_at__isnull=True, expires_at__gt=timezone.now()).update(revoked_at=timezone.now())
    if n:
        audit.log('support.access_revoked', actor=user, organization=ticket.organization, target=ticket)
    return n


def metrics() -> dict:
    since = timezone.now() - timedelta(days=30)
    recent = Ticket.objects.filter(created_at__gte=since, first_response_at__isnull=False)
    avg = recent.aggregate(v=Avg(F('first_response_at') - F('created_at')))['v']
    return {'abertos': Ticket.objects.exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]).count(),
            'sem_resposta': Ticket.objects.filter(first_response_at__isnull=True).exclude(status=Ticket.Status.CLOSED).count(),
            'urgentes': Ticket.objects.filter(priority=Ticket.Priority.URGENT).exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]).count(),
            'primeira_resposta_media_horas_30d': round(avg.total_seconds() / 3600, 1) if avg else None}
