"""Retenção da trilha: expurga eventos antigos preservando a verificabilidade da cadeia."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from audit import service
from audit.models import AuditCheckpoint, AuditEvent


def purge_old_events(days: int | None = None) -> int:
    """
    Apaga eventos mais antigos que ``days`` (padrão ``AUDIT_RETENTION_DAYS``, 365) e grava um
    ``AuditCheckpoint`` com o último hash expurgado — a verificação recomeça dele.
    Em PostgreSQL o trigger de imutabilidade só deixa passar dentro desta função (``audit.allow_purge``).
    """
    days = days or getattr(settings, 'AUDIT_RETENTION_DAYS', 365)
    cutoff = timezone.now() - timedelta(days=days)
    old = AuditEvent.objects.filter(occurred_at__lt=cutoff)
    last = old.order_by('-seq').first()
    if last is None:
        return 0
    count = old.count()
    with transaction.atomic():
        AuditCheckpoint.objects.create(purged_until_seq=last.seq, last_hash=last.hash, purged_count=count,
                                       reason=f'retenção > {days} dias')
        with connection.cursor() as cur:
            if connection.vendor == 'postgresql':
                cur.execute("SET LOCAL audit.allow_purge = 'on'")
            cur.execute('DELETE FROM audit_auditevent WHERE seq <= %s', [last.seq])
    service.log('retention.purged', actor_type='system', changes={'table': 'AuditEvent', 'count': count})
    return count
