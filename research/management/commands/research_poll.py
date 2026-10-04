from django.core.management.base import BaseCommand

from research.monitor import check_all


class Command(BaseCommand):
    help = 'Consulta andamentos novos dos processos monitorados (DataJud). Agendado de hora em hora.'

    def handle(self, *args, **options):
        self.stdout.write(str(check_all()))
