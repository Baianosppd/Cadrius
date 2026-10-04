"""Enfileiramento resiliente (CAD-121): se o broker (Redis) cair, a API responde **503 + Retry-After**
em vez de 500, e o chamador pode desfazer o estado intermediário.
"""
from __future__ import annotations

import logging

from django_q.tasks import async_task
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

RETRY_AFTER_SECONDS = 30


class QueueUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Fila de processamento temporariamente indisponível. Tente novamente em instantes.'
    default_code = 'queue_unavailable'


def enqueue(func, *args, **kwargs):
    """``async_task`` que converte falhas do broker em ``QueueUnavailable`` (HTTP 503)."""
    try:
        return async_task(func, *args, **kwargs)
    except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
        logger.error('Broker indisponível ao enfileirar %s: %s', func, exc.__class__.__name__)
        raise QueueUnavailable() from exc
