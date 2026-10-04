"""Gatilhos: mexeu numa tarefa → enfileira a sincronização (Django-Q). Falha de fila nunca derruba a gravação da tarefa."""
import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from tasks.models import UserTask

logger = logging.getLogger(__name__)


def _enqueue(func, *args):
    try:
        from core.queue import QueueUnavailable, enqueue
        try:
            enqueue(func, *args)
        except QueueUnavailable:
            logger.warning('Fila indisponível: sincronização do Google Calendar adiada (%s)', func)
    except Exception:  # noqa: BLE001
        logger.exception('Falha ao enfileirar sincronização do Google Calendar')


@receiver(post_save, sender=UserTask)
def task_saved(sender, instance, created, **kwargs):
    from gcal.models import GoogleCalendarLink, TaskEventMap
    has_link = GoogleCalendarLink.objects.filter(user_id=instance.responsavel_id, status='active').exists()
    has_event = TaskEventMap.objects.filter(task=instance).exists()
    # só enfileira se há algo a fazer: tarefa sincronizada com conexão ativa, ou evento a remover (desligou a sincronização)
    if (instance.sincronizar and has_link) or has_event:
        _enqueue('gcal.sync.push_task', instance.pk)


@receiver(pre_delete, sender=UserTask)
def task_deleting(sender, instance, **kwargs):
    """pre_delete: o mapeamento ainda existe (o CASCADE o apaga antes do post_delete da tarefa). Só enfileira se a exclusão for confirmada."""
    from gcal.models import TaskEventMap
    mapping = TaskEventMap.objects.filter(task_id=instance.pk).first()
    if mapping is not None:
        link_id, event_id = mapping.link_id, mapping.event_id
        transaction.on_commit(lambda: _enqueue('gcal.sync.delete_event', link_id, event_id))
