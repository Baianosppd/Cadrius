from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from accounts.models import Organization, OrganizationMembership
from privacy import consent
from workflows.models import ExecutionLog


def run(*args):
    out = StringIO()
    call_command('seed_staging', *args, stdout=out)
    return out.getvalue()


class SeedStagingTests(TestCase):
    def test_recusa_fora_de_staging(self):
        with override_settings(DJANGO_ENV='production'), self.assertRaises(CommandError):
            run()

    @override_settings(DJANGO_ENV='staging')
    def test_cria_dados_sinteticos_e_e_idempotente(self):
        first = run()
        self.assertIn('owner@teste.cadrius.ia.br', first)
        self.assertEqual(OrganizationMembership.objects.count(), 4)
        self.assertEqual(Organization.objects.count(), 1)
        self.assertEqual(ExecutionLog.objects.count(), 3)
        owner = OrganizationMembership.objects.get(role='OWNER').user
        self.assertEqual(consent.pending_documents(owner), [])  # já aceitou os termos: pode usar a API
        second = run()
        self.assertNotIn('senha:', second)  # não recria nem reexibe senhas
        self.assertEqual(OrganizationMembership.objects.count(), 4)
        self.assertEqual(ExecutionLog.objects.count(), 3)
