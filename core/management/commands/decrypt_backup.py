from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.utils import _build_fernet


class Command(BaseCommand):
    help = 'Decifra um backup gerado por backup_to_supabase (restauro). Uso: decrypt_backup <arquivo.enc> <saida>'

    def add_arguments(self, parser):
        parser.add_argument('source')
        parser.add_argument('destination')

    def handle(self, *args, source, destination, **options):
        src, dst = Path(source), Path(destination)
        if not src.is_file():
            raise CommandError(f'Arquivo não encontrado: {src}')
        if dst.exists():
            raise CommandError(f'Destino já existe (não sobrescrevo): {dst}')
        dst.write_bytes(_build_fernet().decrypt(src.read_bytes()))
        dst.chmod(0o600)
        self.stdout.write(self.style.SUCCESS(f'Backup decifrado em {dst}'))
