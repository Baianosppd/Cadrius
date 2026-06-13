"""Feed de notificações do sistema (NOTIF-01)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from core.activities import format_relative_time
from emails.models import EmailMessage
from workflows.models import ExecutionLog


@dataclass
class NotificationItem:
    id: int
    title: str
    description: str
    occurred_at: datetime
    read: bool
    type: str
    origem: str
    documento: str
    acao: str
    detalhes: str
    action_label: str
    link: str

    def as_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'time': format_relative_time(self.occurred_at),
            'read': self.read,
            'type': self.type,
            'origem': self.origem,
            'documento': self.documento,
            'acao': self.acao,
            'detalhes': self.detalhes,
            'actionLabel': self.action_label,
            'link': self.link,
        }


def _execution_notification_id(log_id: int) -> int:
    return 10_000_000 + log_id


def _document_notifications(user) -> list[NotificationItem]:
    emails = (
        EmailMessage.objects.filter(
            mailbox__user=user,
            is_dispatched=True,
        )
        .order_by('-created_at')[:50]
    )
    items = []
    for email in emails:
        subject = (email.subject or 'Documento').strip()
        document_label = subject if subject.lower().endswith('.pdf') else f'{subject}.pdf'
        items.append(
            NotificationItem(
                id=email.id,
                title='Documento analisado com sucesso',
                description=f'{subject} foi processada e os prazos foram extraídos.',
                occurred_at=email.created_at,
                read=False,
                type='documento',
                origem='Módulo de Documentos',
                documento=document_label,
                acao='Análise concluída com sucesso',
                detalhes='O conteúdo foi analisado pela IA e encaminhado para automação.',
                action_label='Ir para Módulo de Documentos',
                link='/documentos',
            )
        )
    return items


def _execution_notifications(user) -> list[NotificationItem]:
    logs = (
        ExecutionLog.objects.filter(triggered_by=user)
        .select_related('workflow')
        .order_by('-created_at')[:50]
    )
    items = []
    for log in logs:
        workflow_name = log.workflow.name

        if log.status == 'SUCCESS':
            prazo = _extract_prazo(log.trigger_payload)
            detalhes = (
                'Foram extraídos 3 prazos importantes.'
                if prazo
                else 'A automação foi concluída sem erros.'
            )
            items.append(
                NotificationItem(
                    id=_execution_notification_id(log.id),
                    title='Automação executada com sucesso',
                    description=f'{workflow_name} foi executada com sucesso.',
                    occurred_at=log.created_at,
                    read=False,
                    type='automacao',
                    origem='Módulo de Automações',
                    documento=workflow_name,
                    acao='Execução concluída',
                    detalhes=detalhes,
                    action_label='Ir para Automações',
                    link='/automacoes',
                )
            )
            if prazo:
                processo = _extract_process_number(log.trigger_payload)
                detail = f'Prazo fatal em {prazo}'
                if processo:
                    detail = f'{detail} no processo {processo}.'
                items.append(
                    NotificationItem(
                        id=_execution_notification_id(log.id) + 1,
                        title='Prazo identificado',
                        description=detail,
                        occurred_at=log.created_at,
                        read=False,
                        type='prazo',
                        origem='Módulo de Automações',
                        documento=processo or workflow_name,
                        acao='Prazo registrado',
                        detalhes='Revise os prazos extraídos antes do vencimento.',
                        action_label='Ver prazos',
                        link='/documentos',
                    )
                )
        elif log.status == 'FAILED':
            error_detail = (log.error_message or 'Erro desconhecido.').strip()
            if len(error_detail) > 120:
                error_detail = f'{error_detail[:117]}...'
            items.append(
                NotificationItem(
                    id=_execution_notification_id(log.id),
                    title='Erro na automação',
                    description=f'{workflow_name} falhou durante a execução.',
                    occurred_at=log.created_at,
                    read=False,
                    type='erro',
                    origem='Módulo de Automações',
                    documento=workflow_name,
                    acao='Execução interrompida',
                    detalhes=error_detail,
                    action_label='Ir para Automações',
                    link='/automacoes',
                )
            )
    return items


def _extract_prazo(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    prazo = payload.get('prazo_fatal')
    return str(prazo) if prazo else None


def _extract_process_number(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    processo = payload.get('numero_processo')
    if not processo:
        return None
    return str(processo).strip() or None


def notifications_for_user(user, *, limit: int = 20) -> list[dict]:
    if user is None or not getattr(user, 'is_authenticated', False):
        return []

    items = _document_notifications(user) + _execution_notifications(user)
    items.sort(key=lambda item: item.occurred_at, reverse=True)
    return [item.as_dict() for item in items[:limit]]
