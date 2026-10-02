import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from supabase import Client, create_client

from core.utils import _build_fernet

# Fernet cifra em memória: acima disto use pg_dump | age/gpg em streaming (limite explícito > falha silenciosa).
MAX_BACKUP_BYTES = 512 * 1024 * 1024


class Command(BaseCommand):
    help = (
        'Gera backup do banco (SQLite ou Postgres), CIFRA com ENCRYPTION_KEY e envia ao Supabase. '
        'Dumps contêm dados pessoais: nunca saem em texto puro (LGPD / ISO 27001 A.8.13, A.8.24).'
    )

    def handle(self, *args, **kwargs):
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        bucket_name = os.getenv('SUPABASE_BACKUP_BUCKET', 'cadrius-backups')

        if not supabase_url or not supabase_key:
            raise CommandError('Credenciais do Supabase ausentes (SUPABASE_URL/SUPABASE_KEY).')

        db = settings.DATABASES['default']
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        supabase: Client = create_client(supabase_url, supabase_key)

        # Diretório temporário privado (0700): evita o /tmp partilhado e previsível.
        with tempfile.TemporaryDirectory(prefix='cadrius-backup-') as tmp:
            if 'sqlite3' in db['ENGINE']:
                filename = f'backup_cadrius_{timestamp}.sqlite3'
                dump_path = Path(tmp) / filename
                shutil.copy2(db['NAME'], dump_path)
            elif 'postgresql' in db['ENGINE']:
                filename = f'backup_cadrius_{timestamp}.dump'
                dump_path = Path(tmp) / filename
                env = os.environ.copy()
                if db.get('PASSWORD'):
                    env['PGPASSWORD'] = str(db['PASSWORD'])
                cmd = [
                    'pg_dump', '-U', db['USER'], '-h', db['HOST'], '-p', str(db['PORT'] or 5432),
                    '-F', 'c', '-f', str(dump_path), db['NAME'],
                ]
                try:
                    subprocess.run(cmd, check=True, env=env)  # noqa: S603 - argumentos fixos, sem shell
                except subprocess.CalledProcessError as exc:
                    raise CommandError(f'pg_dump falhou (código {exc.returncode}).') from exc
            else:
                raise CommandError('Motor de banco de dados não suportado para backup automático.')

            size = dump_path.stat().st_size
            if size > MAX_BACKUP_BYTES:
                raise CommandError(f'Dump com {size} bytes excede o limite de cifra em memória.')

            encrypted_path = dump_path.with_suffix(dump_path.suffix + '.enc')
            encrypted_path.write_bytes(_build_fernet().encrypt(dump_path.read_bytes()))
            os.chmod(encrypted_path, 0o600)

            self.stdout.write('Enviando backup cifrado ao Supabase Storage...')
            try:
                with open(encrypted_path, 'rb') as fh:
                    supabase.storage.from_(bucket_name).upload(
                        path=encrypted_path.name,
                        file=fh,
                        file_options={'content-type': 'application/octet-stream'},
                    )
            except Exception as exc:
                raise CommandError(f'Falha no upload do backup: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(f'Backup {filename}.enc salvo (cifrado).'))
