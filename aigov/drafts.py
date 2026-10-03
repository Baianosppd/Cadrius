"""Criação de workflows a partir da saída da IA — sempre como RASCUNHO inativo (RNE-016 / RF-013)."""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from audit import service as audit
from aigov.guard import get_policy
from integrations.ssrf import UnsafeURLError, validate_outbound_url
from workflows.models import Action, Trigger, Workflow

MAX_TEMPLATE_CHARS = 5000
ALLOWED_ACTION_TYPES = {code for code, _ in Action.ACTION_TYPES}


def validate_generated(data: dict, policy) -> dict:
    """Valida/sanitiza a saída da IA ANTES de gravar (a IA pode alucinar ou ser alvo de prompt injection)."""
    actions = data.get('actions') or []
    if not actions:
        raise serializers.ValidationError('A IA não gerou nenhuma ação.')
    if len(actions) > policy.max_actions_per_ai_workflow:
        raise serializers.ValidationError(
            f'A IA gerou {len(actions)} ações; o limite do escritório é {policy.max_actions_per_ai_workflow}.')
    clean = []
    for index, action in enumerate(actions, start=1):
        action_type = str(action.get('action_type'))
        if action_type not in ALLOWED_ACTION_TYPES:
            raise serializers.ValidationError(f'Ação {index}: tipo "{action_type}" não permitido.')
        url = action.get('endpoint_url') or ''
        if action_type == 'WEBHOOK':
            try:
                validate_outbound_url(url, resolve=False)  # revalidado com DNS no envio
            except UnsafeURLError as exc:
                raise serializers.ValidationError(f'Ação {index}: {exc}')
        template = str(action.get('payload_template') or '')
        if not template or len(template) > MAX_TEMPLATE_CHARS:
            raise serializers.ValidationError(f'Ação {index}: template vazio ou maior que {MAX_TEMPLATE_CHARS} caracteres.')
        clean.append({'action_type': action_type, 'endpoint_url': url or None, 'payload_template': template})
    return {
        'name': str(data.get('workflow_name') or 'Automação gerada por IA')[:255],
        'description': str(data.get('workflow_description') or '')[:2000],
        'event_type': str((data.get('trigger') or {}).get('event_type') or 'manual')[:100],
        'payload_mapping': (data.get('trigger') or {}).get('payload_mapping') or {},
        'actions': clean,
    }


@transaction.atomic
def create_ai_draft(*, organization, user, connection, generated: dict) -> Workflow:
    """Grava o workflow como rascunho INATIVO; só um OWNER/ADMIN pode aprová-lo (ativá-lo)."""
    policy = get_policy(organization)
    clean = validate_generated(generated, policy)
    workflow = Workflow.objects.create(
        organization=organization, name=clean['name'], description=clean['description'],
        is_active=False, ai_generated=True,
    )
    Trigger.objects.create(workflow=workflow, connection=connection, event_type=clean['event_type'],
                           payload_mapping=clean['payload_mapping'])
    for action in clean['actions']:
        Action.objects.create(workflow=workflow, method='POST', **action)
    audit.log('ai.draft_created', actor=user, organization=organization, target=workflow,
              changes={'actions': len(clean['actions'])}, data_categories=['processual'], legal_basis='contrato')
    return workflow
