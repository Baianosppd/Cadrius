"""Agendado (setup_security_schedules): busca no DJEN as comunicações das OABs acompanhadas (CAD-173)."""
from django.core.management.base import BaseCommand

from publications.services import poll_all


class Command(BaseCommand):
    help = 'Captura as publicações novas do DJEN para as OABs acompanhadas pelos escritórios.'

    def handle(self, *args, **options):
        out = poll_all()
        self.stdout.write(f"OABs: {out['oabs']} · novas: {out['new']} · com erro: {out['errors']}")
