from django.core.management.base import BaseCommand

from core.storage import encrypted_storage
from documents.models import Document


class Command(BaseCommand):
    help = 'Cifra no disco os documentos antigos (legado em texto puro). Idempotente. --dry-run só conta.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, dry_run=False, **options):
        storage = encrypted_storage()
        total = plain = done = missing = 0
        for doc in Document.objects.exclude(arquivo='').iterator():
            total += 1
            try:
                if storage.is_encrypted(doc.arquivo.name):
                    continue
                plain += 1
                if not dry_run and storage.rewrite_encrypted(doc.arquivo.name):
                    done += 1
            except FileNotFoundError:
                missing += 1
        self.stdout.write(f'{total} arquivos · {plain} em texto puro · {done} cifrados agora · {missing} ausentes no disco')
