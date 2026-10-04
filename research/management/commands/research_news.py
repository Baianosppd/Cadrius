from django.core.management.base import BaseCommand

from research.news import refresh_feeds


class Command(BaseCommand):
    help = 'Atualiza o clipping de notícias jurídicas (fontes em NEWS_FEEDS). Agendado de hora em hora.'

    def handle(self, *args, **options):
        self.stdout.write(str(refresh_feeds()))
