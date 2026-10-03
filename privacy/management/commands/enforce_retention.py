from django.core.management.base import BaseCommand

from privacy.retention import enforce_retention


class Command(BaseCommand):
    help = 'Aplica a política de retenção (e-mails, payloads, logs de integração, organizações encerradas, auditoria).'

    def handle(self, *args, **options):
        for key, value in enforce_retention().items():
            self.stdout.write(f'{key}: {value}')
        self.stdout.write(self.style.SUCCESS('Retenção aplicada.'))
