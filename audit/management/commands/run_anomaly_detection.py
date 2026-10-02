from django.core.management.base import BaseCommand

from audit.detectors import run_detectors


class Command(BaseCommand):
    help = 'Executa as regras de deteção de anomalias sobre a trilha de auditoria.'

    def handle(self, *args, **options):
        created = run_detectors()
        self.stdout.write(self.style.SUCCESS(f'{created} novo(s) alerta(s).'))
