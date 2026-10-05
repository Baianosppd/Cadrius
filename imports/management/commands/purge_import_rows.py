from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from imports.models import ImportJob


class Command(BaseCommand):
    help = 'Apaga o conteúdo lido de importações não concluídas há mais de 7 dias (LGPD: minimização). Agendado diariamente.'

    def handle(self, *args, **options):
        # concluídas/canceladas já não guardam o conteúdo; aqui só as abandonadas no meio do caminho
        old = ImportJob.objects.filter(created_at__lt=timezone.now() - timedelta(days=7),
                                       status__in=[ImportJob.Status.UPLOADED, ImportJob.Status.PREVIEWED])
        n = 0
        for job in old:
            job.rows, job.status, job.finished_at = [], ImportJob.Status.CANCELED, timezone.now()
            job.save(update_fields=['rows', 'status', 'finished_at'])
            n += 1
        self.stdout.write(f'{n} importações limpas')
