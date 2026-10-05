"""Agendado a cada 15 min (setup_security_schedules): prazos chegando, regras de agenda e aprovações vencidas (CAD-172)."""
from django.core.management.base import BaseCommand

from automations.engine import tick


class Command(BaseCommand):
    help = 'Roda as regras de automação por tempo (prazo chegando, agenda) e expira aprovações antigas.'

    def handle(self, *args, **options):
        out = tick()
        self.stdout.write(f"prazos: {out['deadline']} · agenda: {out['schedule']} · aprovações expiradas: {out['expired']}")
