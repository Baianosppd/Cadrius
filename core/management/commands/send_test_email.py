from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Envia um e-mail de teste para validar o SMTP do ambiente (CAD-155). Uso: manage.py send_test_email voce@dominio.com'

    def add_arguments(self, parser):
        parser.add_argument('to')

    def handle(self, *args, to, **options):
        backend = settings.EMAIL_BACKEND.rsplit('.', 2)[-2]
        if backend in ('dummy', 'console', 'locmem'):
            raise CommandError(f'EMAIL_BACKEND={backend}: nada será enviado de verdade. Defina EMAIL_HOST/USER/PASSWORD no .env.')
        send_mail('Teste de e-mail — Cadrius', 'Se você recebeu esta mensagem, o SMTP do Cadrius está funcionando.',
                  settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        self.stdout.write(self.style.SUCCESS(f'E-mail de teste enviado para {to} (via {settings.EMAIL_HOST}).'))
