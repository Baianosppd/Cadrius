"""Feed de atividades recentes do dashboard (ACTIVITY-01)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from emails.models import EmailMessage
from workflows.models import ExecutionLog


@dataclass
class ActivityItem:
    title: str
    description: str
    occurred_at: datetime
    type: str

    def as_dict(self) -> dict:
        return {
            'title': self.title,
            'description': self.description,
            'time': format_relative_time(self.occurred_at),
            'type': self.type,
        }


def format_relative_time(value: datetime) -> str:
    now = timezone.now()
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())

    delta = now - value
    seconds = max(int(delta.total_seconds()), 0)

    if seconds < 60:
        return 'Há instantes'

    minutes = seconds // 60
    if minutes < 60:
        return f'Há {minutes} minuto{"s" if minutes != 1 else ""}'

    hours = minutes // 60
    if hours < 24:
        return f'Há {hours} hora{"s" if hours != 1 else ""}'

    days = hours // 24
    if days < 7:
        return f'Há {days} dia{"s" if days != 1 else ""}'

    weeks = days // 7
    if weeks < 5:
        return f'Há {weeks} semana{"s" if weeks != 1 else ""}'

    months = days // 30
    if months < 12:
        return f'Há {months} mês{"es" if months != 1 else ""}'

    years = days // 365
    return f'Há {years} ano{"s" if years != 1 else ""}'


def _document_activities(user) -> list[ActivityItem]:
    emails = (
        EmailMessage.objects.filter(
            mailbox__user=user,
            is_dispatched=True,
        )
        .select_related('mailbox')
        .order_by('-created_at')[:50]
    )
    items = []
    for email in emails:
        subject = (email.subject or 'Documento').strip()
        items.append(
            ActivityItem(
                title='Documento analisado com sucesso',
                description=f'{subject} foi processada.',
                occurred_at=email.created_at,
                type='success',
            )
        )
    return items


def _execution_activities(user) -> list[ActivityItem]:
    logs = (
        ExecutionLog.objects.filter(triggered_by=user)
        .select_related('workflow')
        .order_by('-created_at')[:50]
    )
    items = []
    for log in logs:
        workflow_name = log.workflow.name

        if log.status == 'SUCCESS':
            items.append(
                ActivityItem(
                    title='Automação executada',
                    description=f'{workflow_name} concluída com sucesso.',
                    occurred_at=log.created_at,
                    type='success',
                )
            )
            prazo = _extract_prazo(log.trigger_payload)
            if prazo:
                processo = _extract_process_number(log.trigger_payload)
                detail = f'Prazo fatal em {prazo}'
                if processo:
                    detail = f'{detail} no processo {processo}.'
                else:
                    detail = f'{detail} identificado em {workflow_name}.'
                items.append(
                    ActivityItem(
                        title='Prazo identificado',
                        description=detail,
                        occurred_at=log.created_at,
                        type='warning',
                    )
                )
        elif log.status == 'FAILED':
            error_detail = (log.error_message or 'Erro desconhecido.').strip()
            if len(error_detail) > 120:
                error_detail = f'{error_detail[:117]}...'
            items.append(
                ActivityItem(
                    title='Erro na automação',
                    description=f'{workflow_name}: {error_detail}',
                    occurred_at=log.created_at,
                    type='error',
                )
            )
    return items


def _extract_prazo(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    prazo = payload.get('prazo_fatal')
    if not prazo:
        return None
    return str(prazo)


def _extract_process_number(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    processo = payload.get('numero_processo')
    if not processo:
        return None
    return str(processo).strip() or None


def recent_activities_for_user(user, *, limit: int = 20) -> list[dict]:
    if user is None or not getattr(user, 'is_authenticated', False):
        return []

    items = _document_activities(user) + _execution_activities(user)
    items.sort(key=lambda item: item.occurred_at, reverse=True)
    return [item.as_dict() for item in items[:limit]]
