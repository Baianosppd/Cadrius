from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from integrations.models import AppConnection
from core.utils import encrypt_data

User = get_user_model()

class Command(BaseCommand):
    help = 'Popula o banco com dados agnósticos para desenvolvimento'

    def handle(self, *args, **kwargs):
        self.stdout.write("Plantando a semente no banco de dados... 🌱")

        # 1. Superusuário
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@cadrius.com', 'admin123')
            self.stdout.write(self.style.SUCCESS("✅ Superusuário criado."))

        # 2. Conexões Genéricas (Mock)
        apps_para_criar = [
            {'name': 'ERP Jurídico Dev', 'provider': 'generic_erp', 'token': 'TOKEN_ERP_123'},
            {'name': 'Mensageiro Dev', 'provider': 'generic_chat', 'token': 'TOKEN_CHAT_456'}
        ]

        for app in apps_para_criar:
            obj, created = AppConnection.objects.get_or_create(
                name=app['name'],
                defaults={
                    'provider': app['provider'],
                    'credentials': encrypt_data(app['token']),
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"✅ Conexão genérica '{app['name']}' criada."))
            else:
                self.stdout.write(self.style.WARNING(f"⚠️ Conexão '{app['name']}' já existe."))

        self.stdout.write(self.style.SUCCESS("🎉 Seed 100% agnóstico finalizado!"))