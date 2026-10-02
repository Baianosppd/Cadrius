from django.core.management.base import BaseCommand

from audit.retention import purge_old_events


class Command(BaseCommand):
    help = 'Expurga eventos de auditoria além da retenção (AUDIT_RETENTION_DAYS) mantendo a cadeia verificável.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None)

    def handle(self, *args, days=None, **options):
        self.stdout.write(self.style.SUCCESS(f'{purge_old_events(days)} evento(s) expurgado(s).'))
