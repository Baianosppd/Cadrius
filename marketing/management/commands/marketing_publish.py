"""Agendado a cada 15 min: publica conteúdos agendados (Facebook/Instagram) e lembra dos canais sem publicação automática (CAD-174)."""
from django.core.management.base import BaseCommand

from marketing.services import publish_due


class Command(BaseCommand):
    help = 'Publica os conteúdos de marketing agendados que venceram.'

    def handle(self, *args, **options):
        out = publish_due()
        self.stdout.write(f"publicados: {out['publicados']} · falhas: {out['falhas']} · lembretes: {out['lembretes']}")
