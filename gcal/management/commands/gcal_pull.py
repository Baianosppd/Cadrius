from django.core.management.base import BaseCommand

from gcal.sync import pull_all


class Command(BaseCommand):
    help = 'Sincroniza o Google Calendar → tarefas (todas as conexões ativas). Agendado a cada 15 min pelo setup_security_schedules.'

    def handle(self, *args, **options):
        self.stdout.write(str(pull_all()))
