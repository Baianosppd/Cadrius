import os
import shutil
import subprocess
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from supabase import create_client, Client

class Command(BaseCommand):
    help = 'Gera backup do banco (SQLite ou Postgres) e envia para o Supabase'

    def handle(self, *args, **kwargs):
        self.stdout.write("Iniciando processo de backup... ⏳")

        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        bucket_name = 'cadrius-backups'

        if not supabase_url or not supabase_key:
            self.stderr.write("❌ ERRO: Credenciais do Supabase ausentes no .env")
            return

        db_engine = settings.DATABASES['default']['ENGINE']
        db_name = settings.DATABASES['default']['NAME']
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

        supabase: Client = create_client(supabase_url, supabase_key)

        # ---------------------------------------------------------
        # CENÁRIO 1: BACKUP PARA SQLITE (Seu cenário atual)
        # ---------------------------------------------------------
        if 'sqlite3' in db_engine:
            self.stdout.write("💾 Banco SQLite detectado. Fazendo cópia segura do arquivo...")
            filename = f"backup_cadrius_{timestamp}.sqlite3"
            filepath = f"/tmp/{filename}"
            
            try:
                # Faz uma cópia do banco para a pasta tmp para não travar o sistema
                shutil.copy2(db_name, filepath)
                
                self.stdout.write("☁️ Enviando para o Supabase Storage...")
                with open(filepath, 'rb') as f:
                    supabase.storage.from_(bucket_name).upload(
                        path=filename, 
                        file=f, 
                        file_options={"content-type": "application/vnd.sqlite3"}
                    )
                self.stdout.write(self.style.SUCCESS(f"✅ Backup {filename} salvo com sucesso no Supabase!"))
                
            except Exception as e:
                self.stderr.write(f"❌ Erro no backup SQLite: {e}")
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)

        # ---------------------------------------------------------
        # CENÁRIO 2: BACKUP PARA POSTGRESQL (Futuro da sua infra)
        # ---------------------------------------------------------
        elif 'postgresql' in db_engine:
            self.stdout.write("🐘 Banco PostgreSQL detectado. Gerando dump...")
            db_user = settings.DATABASES['default']['USER']
            db_host = settings.DATABASES['default']['HOST']
            db_port = settings.DATABASES['default']['PORT']
            db_pass = settings.DATABASES['default']['PASSWORD']
            
            filename = f"backup_cadrius_{timestamp}.sql"
            filepath = f"/tmp/{filename}"

            dump_command = [
                'pg_dump', '-U', db_user, '-h', db_host, '-p', str(db_port),
                '-F', 'c', '-f', filepath, db_name
            ]

            env = os.environ.copy()
            if db_pass:
                env['PGPASSWORD'] = str(db_pass)

            try:
                subprocess.run(dump_command, check=True, env=env)
                
                self.stdout.write("☁️ Enviando para o Supabase Storage...")
                with open(filepath, 'rb') as f:
                    supabase.storage.from_(bucket_name).upload(
                        path=filename, file=f, file_options={"content-type": "application/x-sql"}
                    )
                self.stdout.write(self.style.SUCCESS(f"✅ Backup {filename} salvo com sucesso no Supabase!"))
                
            except subprocess.CalledProcessError as e:
                self.stderr.write(f"❌ Erro ao rodar pg_dump: {e}")
            except Exception as e:
                self.stderr.write(f"❌ Erro no upload: {e}")
            finally:
                if os.path.exists(filepath):
                    os.remove(filepath)
        else:
            self.stderr.write("❌ Motor de banco de dados não suportado para backup automático.")