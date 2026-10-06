from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Lança as despesas fixas do mês (CAD-223). Idempotente: pode rodar várias vezes ao dia.'

    def handle(self, *args, **options):
        from carteira.reports import generate_recurring
        self.stdout.write(f'despesas fixas lançadas: {generate_recurring()}')
