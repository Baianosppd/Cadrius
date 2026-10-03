"""Atendimento a direitos do titular: exportação, anonimização/eliminação e offboarding de organização."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from audit import service as audit
from audit.models import AuditEvent
from privacy.models import ConsentRecord, DataSubjectRequest, OrganizationOffboarding

logger = logging.getLogger('privacy')
User = get_user_model()

OFFBOARDING_GRACE_DAYS = 30


def open_request(user, type_, notes='', organization=None) -> DataSubjectRequest:
    req = DataSubjectRequest.objects.create(
        user=user, user_ref=str(user.pk), type=type_, notes=notes[:2000],
        organization_id=getattr(organization, 'pk', None),
    )
    audit.log('dsr.opened', actor=user, target=req, changes={'type': type_}, data_categories=['identificacao'],
              legal_basis='obrigacao_legal')
    return req


def export_user_data(user) -> dict:
    """Exportação (acesso/portabilidade — art. 18, II e V). Só dados do PRÓPRIO titular."""
    from emails.models import MailBox
    from tasks.models import UserTask

    memberships = [
        {'organization': m.organization.name, 'role': m.role, 'active': m.is_active, 'joined_at': m.joined_at}
        for m in user.memberships.select_related('organization')
    ]
    data = {
        'generated_at': timezone.now(),
        'profile': {
            'email': user.email, 'first_name': user.first_name, 'last_name': user.last_name,
            'cpf': user.cpf, 'phone': user.phone, 'oab_number': user.oab_number, 'oab_uf': user.oab_uf,
            'practice_area': user.practice_area, 'date_joined': user.date_joined,
        },
        'memberships': memberships,
        'consents': list(ConsentRecord.objects.filter(user_ref=str(user.pk)).values(
            'document__kind', 'document__version', 'purpose', 'granted', 'occurred_at', 'method')),
        'mailboxes': list(MailBox.objects.filter(user=user).values('name', 'imap_host', 'username', 'is_active')),
        'tasks': list(UserTask.objects.filter(responsavel=user).values('titulo', 'scheduled_at', 'completed')),
        'privacy_requests': list(DataSubjectRequest.objects.filter(user_ref=str(user.pk)).values(
            'type', 'status', 'opened_at', 'due_at', 'fulfilled_at')),
        'activity_log': list(AuditEvent.objects.filter(actor_id=str(user.pk)).order_by('-seq')
                             .values('occurred_at', 'action', 'outcome')[:500]),
    }
    audit.log('data.export', actor=user, changes={'scope': 'self_export'}, data_categories=['identificacao', 'contato'],
              legal_basis='obrigacao_legal')
    return data


@transaction.atomic
def anonymize_user(user, *, handled_by='') -> None:
    """
    Eliminação/anonimização da conta (art. 18, IV/VI). Remove identificadores diretos e credenciais.
    Preserva — de forma pseudonimizada — o que a lei permite manter: trilha de auditoria de segurança
    (art. 16, I/II; art. 7º, IX) e prova de consentimentos.
    """
    from emails.models import MailBox
    from integrations.models import AppConnection

    ref = str(user.pk)
    # Credenciais e conteúdo que o utilizador trouxe (caixas de e-mail e conexões próprias).
    mailboxes = MailBox.objects.filter(user=user)
    email_count = sum(m.emails.count() for m in mailboxes)
    mailboxes.delete()  # cascade apaga EmailMessage
    AppConnection.objects.filter(user=user).delete()

    if user.profile_picture:
        user.profile_picture.delete(save=False)
    user.email = f'anon-{ref}@anonimizado.invalid'
    user.username = f'anon-{ref}'
    user.first_name = user.last_name = ''
    user.cpf = None
    user.phone = user.oab_number = user.oab_uf = user.practice_area = None
    user.is_active = False
    user.set_unusable_password()
    user.save()
    user.memberships.update(is_active=False)

    audit.log('anonymization.run', actor_type='system', target_type='User', target_id=ref,
              changes={'emails_removed': email_count, 'handled_by': handled_by},
              data_categories=['identificacao', 'contato'], legal_basis='obrigacao_legal')


def fulfill_request(req: DataSubjectRequest, *, handler_id='', resolution='') -> DataSubjectRequest:
    if req.type in (DataSubjectRequest.Type.DELETION, DataSubjectRequest.Type.ANONYMIZATION) and req.user:
        anonymize_user(req.user, handled_by=handler_id)
    req.status = DataSubjectRequest.Status.FULFILLED
    req.fulfilled_at = timezone.now()
    req.handled_by = handler_id
    req.resolution = resolution[:2000]
    req.save()
    audit.log('dsr.fulfilled', actor_type='system', target=req, changes={'type': req.type, 'handler': handler_id},
              legal_basis='obrigacao_legal')
    return req


def reject_request(req: DataSubjectRequest, *, handler_id='', resolution='') -> DataSubjectRequest:
    req.status = DataSubjectRequest.Status.REJECTED
    req.fulfilled_at = timezone.now()
    req.handled_by = handler_id
    req.resolution = resolution[:2000]
    req.save()
    audit.log('dsr.rejected', actor_type='system', target=req, changes={'type': req.type, 'handler': handler_id},
              legal_basis='obrigacao_legal')
    return req


# ------------------------------------------------------------------ offboarding de organização (RNE-013)
def request_organization_closure(organization, requested_by) -> OrganizationOffboarding:
    """Desativa o escritório e agenda a eliminação para daqui a 30 dias (recuperável até lá)."""
    organization.is_active = False
    organization.save(update_fields=['is_active'])
    off = OrganizationOffboarding.objects.create(
        organization_id=organization.pk, organization_name=organization.name, requested_by=str(requested_by.pk),
        purge_after=timezone.now() + timedelta(days=OFFBOARDING_GRACE_DAYS),
    )
    audit.log('org.updated', actor=requested_by, organization=organization,
              changes={'closure_requested': True, 'purge_after': off.purge_after.date().isoformat()})
    return off


def cancel_organization_closure(offboarding: OrganizationOffboarding, by) -> None:
    from accounts.models import Organization

    offboarding.status = OrganizationOffboarding.Status.CANCELLED
    offboarding.save(update_fields=['status'])
    Organization.objects.filter(pk=offboarding.organization_id).update(is_active=True)
    audit.log('org.updated', actor=by, changes={'closure_cancelled': True})


@transaction.atomic
def purge_organization(offboarding: OrganizationOffboarding) -> dict:
    """Elimina definitivamente o escritório e os dados que só existiam por causa dele."""
    from accounts.models import Organization
    from emails.models import MailBox
    from integrations.models import AppConnection

    org = Organization.objects.filter(pk=offboarding.organization_id).first()
    summary = {'workflows': 0, 'mailboxes': 0, 'connections': 0, 'members': 0}
    if org is not None:
        member_ids = list(org.members.values_list('user_id', flat=True))
        summary['members'] = len(member_ids)
        summary['workflows'] = org.workflows.count()
        # Utilizadores que pertencem SÓ a este escritório: seus recursos (caixas/conexões) saem junto.
        only_here = [
            uid for uid in member_ids
            if not User.objects.get(pk=uid).memberships.exclude(organization=org).exists()
        ]
        boxes = MailBox.objects.filter(user_id__in=only_here)
        summary['mailboxes'] = boxes.count()
        boxes.delete()
        conns = AppConnection.objects.filter(user_id__in=only_here)
        summary['connections'] = conns.count()
        conns.delete()
        org.delete()  # cascade: memberships, workflows, execution logs…
    offboarding.status = OrganizationOffboarding.Status.PURGED
    offboarding.purged_at = timezone.now()
    offboarding.summary = summary
    offboarding.save()
    audit.log('retention.purged', actor_type='system', organization=None,
              changes={'organization_id': str(offboarding.organization_id), **summary}, legal_basis='obrigacao_legal')
    return summary
