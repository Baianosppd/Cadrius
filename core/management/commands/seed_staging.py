"""Popula o ambiente de TESTE (staging) com dados 100% sintéticos — nunca dados reais (LGPD)."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Organization, OrganizationMembership
from audit import service as audit
from billing.models import SubscriptionPlan
from privacy import consent
from workflows.models import Action, ExecutionLog, Trigger, Workflow

User = get_user_model()

USERS = [
    ('owner', 'OWNER', 'Dona (Teste)'),
    ('admin', 'ADMIN', 'Administrador (Teste)'),
    ('membro', 'MEMBER', 'Advogada (Teste)'),
    ('leitor', 'VIEWER', 'Estagiário (Teste)'),
]


class Command(BaseCommand):
    help = (
        'Cria escritório de teste, usuários por cargo, workflows e execuções SINTÉTICOS. '
        'Só roda com DJANGO_ENV=staging (ou --force). Idempotente: não duplica.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Ignora a trava de ambiente (não use em produção).')
        parser.add_argument('--domain', default='teste.cadrius.ia.br', help='Domínio dos e-mails fictícios.')

    def handle(self, *args, force=False, domain='teste.cadrius.ia.br', **options):
        env = getattr(settings, 'DJANGO_ENV', None) or __import__('os').environ.get('DJANGO_ENV', '')
        if env != 'staging' and not force:
            raise CommandError(f'Recusado: DJANGO_ENV={env!r}. Este comando só roda em staging (use --force só em dev).')

        plan, _ = SubscriptionPlan.objects.get_or_create(
            tier='PRO', defaults=dict(name='Plano Pro (teste)', price_brl=0, max_users=10, max_ai_extractions=500))
        org, _ = Organization.objects.get_or_create(
            name='Escritório Demo (TESTE)', defaults=dict(plan=plan, nome_fantasia='Demo Advocacia'))
        org.allowed_domain = org.allowed_domain or domain
        org.save()

        credentials = []
        for handle, role, label in USERS:
            email = f'{handle}@{domain}'
            user = User.objects.filter(email=email).first()
            if user is None:
                password = secrets.token_urlsafe(12) + 'aA1!'
                user = User.objects.create_user(username=email, email=email, password=password, first_name=label)
                credentials.append((email, role, password))
            OrganizationMembership.objects.get_or_create(user=user, organization=org, defaults={'role': role})
            for doc in consent.current_documents(consent.REQUIRED_KINDS):
                if not consent.pending_documents(user):
                    break
                consent.record_consent(user, doc, method='api')

        owner = User.objects.get(email=f'owner@{domain}')
        if not Workflow.objects.filter(organization=org).exists():
            from integrations.models import AppConnection
            conn = AppConnection.objects.create(user=owner, name='Webhook de teste', app_name='WEBHOOK')
            wf = Workflow.objects.create(name='Avisar prazo (exemplo)', organization=org, description='Dados fictícios')
            Trigger.objects.create(workflow=wf, connection=conn, event_type='Webhook Externo')
            Action.objects.create(workflow=wf, action_type='WEBHOOK', endpoint_url='https://example.com/hook',
                                  method='POST', payload_template='{"processo": "{{numero_processo}}"}')
            for i, status in enumerate(['SUCCESS', 'SUCCESS', 'FAILED']):
                log = ExecutionLog.objects.create(workflow=wf, status=status, trigger_payload={'numero_processo': f'000{i}-FICTICIO'},
                                                  execution_time_ms=800 + i * 300)
                ExecutionLog.objects.filter(pk=log.pk).update(created_at=timezone.now() - timedelta(days=i))
            audit.log('workflow.created', actor=owner, organization=org, target=wf, reason='seed_staging')

        self.stdout.write(self.style.SUCCESS('Base de teste pronta (dados sintéticos).'))
        if credentials:
            self.stdout.write('\nUSUÁRIOS CRIADOS (anote agora — as senhas não são exibidas de novo):')
            for email, role, password in credentials:
                self.stdout.write(f'  {role:<7} {email}  senha: {password}')
