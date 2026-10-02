"""CAD-066: regressões dos defeitos encontrados na auditoria de código."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase

from accounts.adapters import B2BSocialAccountAdapter, _email_is_verified
from accounts.models import OrganizationMembership
from cadrius.tests_security import make_org, make_user
from extraction.schemas import get_extraction_schema, list_extraction_schemas
from integrations.models import AppConnection
from workflows.models import Action, Workflow


class HealthTests(TestCase):
    def test_healthz_nao_vaza_detalhes(self):
        resp = self.client.get('/healthz/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json()), {'status', 'db_status', 'app_version'})

    def test_healthz_erro_devolve_503_sem_excecao(self):
        with mock.patch('core.views.connection.cursor', side_effect=RuntimeError('senha=secreta')):
            resp = self.client.get('/healthz/', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 503)
        self.assertNotIn('secreta', resp.content.decode())

    def test_readyz(self):
        resp = self.client.get('/readyz/', HTTP_HOST='localhost')
        self.assertIn(resp.status_code, (200, 503))
        self.assertEqual(resp.json()['checks']['database'], 'ok')


class SsoAdapterTests(TestCase):
    def test_modulo_importa_e_exige_email_verificado(self):
        # Regressão: `from billing.models import Organization` quebrava TODO login SSO (ImportError).
        verified = SimpleNamespace(email_addresses=[SimpleNamespace(email='a@b.com', verified=True)])
        unverified = SimpleNamespace(email_addresses=[SimpleNamespace(email='a@b.com', verified=False)])
        self.assertTrue(_email_is_verified(verified, 'A@b.com'))
        self.assertFalse(_email_is_verified(unverified, 'a@b.com'))
        self.assertFalse(_email_is_verified(SimpleNamespace(email_addresses=[]), 'a@b.com'))

    def test_auto_vinculo_por_dominio_somente_com_email_verificado(self):
        org = make_org('Escritório X')
        org.allowed_domain = 'escritorio.com'
        org.save()
        for verified, expected in ((False, 0), (True, 1)):
            user = make_user(f'u{int(verified)}@escritorio.com')
            sociallogin = SimpleNamespace(
                email_addresses=[SimpleNamespace(email=user.email, verified=verified)],
            )
            with mock.patch(
                'allauth.socialaccount.adapter.DefaultSocialAccountAdapter.save_user',
                return_value=user,
            ):
                B2BSocialAccountAdapter().save_user(None, sociallogin)
            self.assertEqual(OrganizationMembership.objects.filter(user=user, organization=org).count(), expected)


class ExtractionRegistryTests(SimpleTestCase):
    def test_so_aceita_schemas_pydantic_do_dominio(self):
        self.assertIsNotNone(get_extraction_schema('ProcessoJuridicoSchema'))
        for bad in ('date', 'BaseModel', 'Literal', 'os', '', None, '__builtins__'):
            self.assertIsNone(get_extraction_schema(bad), bad)
        self.assertIn('ProcessoJuridicoSchema', list_extraction_schemas())


class WorkflowApiTests(APITestCase):
    def setUp(self):
        self.org = make_org('A')
        self.owner = make_user('owner@a.com', self.org, role='OWNER')
        self.conn = AppConnection.objects.create(user=self.owner, name='c', app_name='WEBHOOK')
        self.client.force_authenticate(self.owner)

    def payload(self, **action):
        return {
            'name': 'WF', 'description': 'd',
            'trigger': {'connection': self.conn.pk, 'event_type': 'manual', 'payload_mapping': {}},
            'actions': [{
                'action_type': 'WEBHOOK', 'endpoint_url': 'https://example.com/hook',
                'method': 'POST', 'payload_template': '{"a": "{{x}}"}', **action,
            }],
        }

    def test_crud_funciona_e_associa_ao_escritorio(self):
        # Regressão: ActionSerializer referenciava campos inexistentes e o endpoint dava 500.
        resp = self.client.post('/api/workflows/automations/', self.payload(), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        wf = Workflow.objects.get(pk=resp.data['id'])
        self.assertEqual(wf.organization, self.org)
        self.assertEqual(Action.objects.filter(workflow=wf).count(), 1)
        self.assertEqual(self.client.get('/api/workflows/automations/').status_code, 200)

    def test_rejeita_url_de_acao_insegura(self):
        resp = self.client.post(
            '/api/workflows/automations/', self.payload(endpoint_url='file:///etc/passwd'), format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejeita_conexao_de_outro_escritorio(self):
        other = make_user('x@b.com', make_org('B'), role='OWNER')
        foreign = AppConnection.objects.create(user=other, name='f', app_name='WEBHOOK')
        data = self.payload()
        data['trigger']['connection'] = foreign.pk
        resp = self.client.post('/api/workflows/automations/', data, format='json')
        self.assertEqual(resp.status_code, 400)
