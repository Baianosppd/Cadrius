from django.core.management.base import BaseCommand
from django_q.models import Schedule

class Command(BaseCommand):
    help = 'Configura e agenda a rotina automática de backup da base de dados'

    def handle(self, *args, **kwargs):
        self.stdout.write("A configurar rotinas de infraestrutura... ⏳")

        schedule, created = Schedule.objects.get_or_create(
            func='django.core.management.call_command',
            args='"backup_to_supabase"',
            defaults={
                'name': 'Backup Diário Supabase',
                'schedule_type': Schedule.DAILY,
                'repeats': -1 # Repete infinitamente
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS("✅ Escudo ativado: Rotina de Backup no Supabase agendada!"))
        else:
            self.stdout.write(self.style.WARNING("⚠️ A rotina de Backup já se encontrava agendada."))