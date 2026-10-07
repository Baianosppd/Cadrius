"""API única de auditoria:  ``audit.service.log(action, ...)`` — nunca derruba o pedido."""
from __future__ import annotations

import logging
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from audit.context import get_context
from audit.models import GENESIS_HASH, AuditChainHead, AuditEvent
from audit.redaction import mask_email, redact

logger = logging.getLogger('audit')

# Catálogo fechado de ações (categoria.verbo). Novas ações devem ser acrescentadas aqui.
ACTIONS = frozenset({
    # autenticação & sessão
    'auth.login.success', 'auth.login.failure', 'auth.login.locked', 'auth.logout',
    'auth.password.change', 'auth.password.reset_requested', 'auth.password.reset', 'auth.token.refresh', 'auth.sso.login', 'auth.register',
    'auth.mfa.enabled', 'auth.mfa.disabled', 'auth.mfa.failed', 'auth.mfa.recovery_regenerated', 'auth.mfa.reset',
    # conta, equipa e acesso
    'user.updated', 'member.invited', 'member.role_changed', 'member.removed', 'org.updated',
    'admin.login', 'admin.access', 'admin.add', 'admin.change', 'admin.delete',
    # dados
    'data.read', 'data.bulk_read', 'data.export', 'data.download',
    'workflow.created', 'workflow.updated', 'workflow.deleted', 'workflow.approved', 'workflow.activated',
    'mailbox.created', 'mailbox.updated', 'mailbox.deleted',
    'extractionprofile.created', 'extractionprofile.updated', 'extractionprofile.deleted',
    'connection.created', 'connection.updated', 'connection.deleted',
    # processamento por terceiros
    'ai.request', 'ai.blocked', 'ai.draft_created', 'integration.call', 'message.sent',
    'webhook.accepted', 'webhook.invalid_token',
    # privacidade
    'consent.granted', 'consent.revoked', 'dsr.opened', 'dsr.fulfilled', 'dsr.rejected',
    'retention.purged', 'anonymization.run',
    # segurança
    'anomaly.detected', 'anomaly.reviewed', 'ratelimit.hit', 'permission.denied',
    'audit.viewed', 'audit.export', 'audit.chain_broken', 'audit.chain_verified',
    'billing.checkout', 'billing.payment_confirmed', 'billing.payment_failed', 'billing.subscription_canceled',
    'billing.credits_purchased', 'billing.admin_changed', 'billing.price_changed',
    'document.extracted', 'document.extraction_confirmed', 'document.blocked',
    'ai.autonomy_changed', 'ai.rule_decided', 'memory.added', 'memory.deleted',
    'compliance.assessment_updated', 'org.closure',
    'backoffice.action', 'contact.created', 'contact.updated', 'contact.deleted', 'data.import',
    'support.ticket_opened', 'support.staff_reply', 'support.access_granted', 'support.access_revoked',
    'research.case_added', 'research.case_removed', 'research.movements_found',
    'automation.rule_created', 'automation.rule_updated', 'automation.rule_deleted', 'automation.rule_enabled',
    'automation.rule_disabled', 'automation.run_approved', 'automation.run_rejected',
    'publication.captured', 'publication.reviewed', 'publication.watch_added', 'publication.watch_removed',
    'draft.created', 'draft.updated', 'draft.deleted', 'draft.exported', 'draft.template_saved',
    'automation.suggestion_decided', 'automation.discovery', 'brain.profile_updated', 'connection.tested', 'signature.requested', 'billing.charge_created',
    'marketing.content_created', 'marketing.content_updated', 'marketing.content_deleted', 'marketing.content_published',
    'marketing.campaign_saved', 'marketing.image_generated',
    'crm.opportunity_saved', 'crm.stage_changed', 'crm.agreement_created', 'crm.agreement_canceled', 'crm.success_registered',
    'finance.receivable_saved', 'finance.receivable_paid', 'finance.receivable_reopened', 'finance.expense_created',
    'finance.expense_deleted', 'finance.webhook_configured',
    'portal.link_created', 'portal.link_revoked', 'portal.viewed',
    'fiscal.nfse_requested', 'fiscal.nfse_canceled', 'fiscal.obligation_done',
    'assistant.action', 'assistant.mcp_call', 'assistant.token_created', 'assistant.token_revoked', 'assistant.key_saved',
    'assistant.key_removed', 'auth.password.temp_set', 'auth.password.forced_change', 'security.ip_blocked', 'security.ip_unblocked',
    # CAD-223
    'team.access_group_saved', 'team.access_group_deleted', 'team.access_assigned', 'staff.areas_changed',
    'finance.recurring_saved', 'finance.recurring_deleted', 'finance.settings_saved', 'fiscal.office_nfse_requested',
    'marketing.form_saved', 'marketing.lead_captured', 'marketing.survey_answered',
    'support.customization_requested', 'support.customization_updated',
    'forense.suspension_saved', 'forense.suspension_deleted', 'contact.cnpj_lookup',
    # CAD-224
    'ai.route_changed', 'billing.coupon_saved', 'billing.coupon_applied',
})


def log(
    action: str,
    *,
    actor=None,
    organization=None,
    target=None,
    target_type: str = '',
    target_id: str = '',
    outcome: str = AuditEvent.Outcome.SUCCESS,
    reason: str = '',
    changes: dict | None = None,
    data_categories: Iterable[str] = (),
    legal_basis: str = '',
    actor_type: str | None = None,
    actor_label: str | None = None,
) -> AuditEvent | None:
    """
    Regista um evento. Falhas de auditoria NÃO propagam (log + Sentry), para não derrubar a operação
    do utilizador — mas ficam visíveis: ``audit.failure`` em logs e no Sentry.
    """
    try:
        if action not in ACTIONS:
            raise ValueError(f'Ação de auditoria desconhecida: {action}')

        ctx = get_context()
        a_type, a_id, a_label = ctx.actor_type, ctx.actor_id, ctx.actor_label
        org_id = ctx.organization_id

        if actor is not None:  # ator explícito tem prioridade sobre o contexto
            a_type = 'admin' if getattr(actor, 'is_staff', False) else 'user'
            a_id = str(actor.pk)
            a_label = mask_email(getattr(actor, 'email', '') or '')
        if actor_type:
            a_type = actor_type
        if actor_label is not None:
            a_label = actor_label
        if organization is not None:
            org_id = str(organization.pk)
        if target is not None:
            target_type = target_type or target.__class__.__name__
            target_id = target_id or str(getattr(target, 'pk', ''))

        with transaction.atomic():
            head, _ = AuditChainHead.objects.select_for_update().get_or_create(id=1)
            event = AuditEvent(
                occurred_at=timezone.now(),
                request_id=ctx.request_id,
                actor_type=a_type, actor_id=a_id, actor_label=a_label,
                organization_id=org_id,
                action=action, target_type=target_type[:64], target_id=str(target_id)[:64],
                outcome=outcome, reason=(reason or '')[:255],
                ip=ctx.ip, user_agent_hash=ctx.user_agent_hash, auth_method=ctx.auth_method,
                changes=redact(changes or {}),
                data_categories=list(data_categories),
                legal_basis=legal_basis,
                prev_hash=head.last_hash or GENESIS_HASH,
            )
            event.hash = event.compute_hash()
            event.save()
            head.last_seq, head.last_hash = event.seq, event.hash
            head.save(update_fields=['last_seq', 'last_hash'])
        return event
    except Exception:  # noqa: BLE001 — auditoria nunca derruba a operação
        logger.exception('audit.failure: não foi possível registar o evento %s', action)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception()
        except Exception:  # noqa: BLE001
            pass
        return None
