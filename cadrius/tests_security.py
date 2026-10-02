"""Testes de regressão de segurança (blindagem pós-auditoria)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase

from accounts.models import Organization, OrganizationMembership
from billing.models import SubscriptionPlan
from core.utils import decrypt_data, encrypt_data
from emails.models import MailBox
from integrations.models import AppConnection
from integrations.ssrf import UnsafeURLError, validate_outbound_url
from workflows.tasks import parse_action_template_to_dict

User = get_user_model()


def legal_acceptance():
    """Campos de aceite exigidos no cadastro (versões vigentes dos documentos legais)."""
    from privacy.models import LegalDocument
    return {
        f'accepted_{d.kind}_version': d.version
        for d in LegalDocument.objects.filter(is_current=True, kind__in=['terms', 'privacy', 'ciencia'])
    }


def make_org(name='Escritório'):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        tier='FREE', defaults=dict(name='Free', price_brl=0, max_users=10, max_ai_extractions=100),
    )
    return Organization.objects.create(name=name, plan=plan)


def make_user(email, org=None, role='MEMBER', password='Str0ng-Passw0rd!x'):
    user = User.objects.create_user(username=email, email=email, password=password)
    if org is not None:
        OrganizationMembership.objects.create(user=user, organization=org, role=role)
    return user


class CryptoTests(TestCase):
    def test_roundtrip_e_legado(self):
        token = encrypt_data('segredo')
        self.assertTrue(token.startswith('enc::'))
        self.assertNotIn('segredo', token)
        self.assertEqual(decrypt_data(token), 'segredo')
        self.assertEqual(decrypt_data('texto-legado'), 'texto-legado')

    def test_senha_imap_e_credenciais_ficam_cifradas_na_base(self):
        user = make_user('crypto@example.com')
        box = MailBox.objects.create(user=user, name='cx', imap_host='h', username='u', password='senha-imap')
        conn = AppConnection.objects.create(
            user=user, name='c', app_name='WEBHOOK', credentials={'token': 'abc123'},
        )
        with connection.cursor() as cur:
            cur.execute('SELECT password FROM emails_mailbox WHERE id=%s', [box.id])
            raw_pw = cur.fetchone()[0]
            cur.execute('SELECT credentials FROM integrations_appconnection WHERE id=%s', [conn.id])
            raw_cred = cur.fetchone()[0]
        self.assertTrue(raw_pw.startswith('enc::'))
        self.assertNotIn('senha-imap', raw_pw)
        self.assertTrue(raw_cred.startswith('enc::'))
        self.assertNotIn('abc123', raw_cred)
        box.refresh_from_db()
        conn.refresh_from_db()
        self.assertEqual(box.password, 'senha-imap')
        self.assertEqual(conn.credentials, {'token': 'abc123'})


@override_settings(OUTBOUND_ALLOW_PRIVATE_NETWORKS=False)
class SsrfTests(SimpleTestCase):
    def test_bloqueia_destinos_internos_e_esquemas_invalidos(self):
        for url in (
            'http://127.0.0.1:6379/', 'http://localhost/', 'http://169.254.169.254/latest/meta-data/',
            'http://10.0.0.5/', 'http://[::1]/', 'file:///etc/passwd', 'gopher://x/', 'ftp://example.com/',
            'http://user:pass@8.8.8.8/', '',
        ):
            with self.subTest(url=url), self.assertRaises(UnsafeURLError):
                validate_outbound_url(url)

    def test_permite_ip_publico(self):
        self.assertEqual(validate_outbound_url('https://8.8.8.8/hook'), 'https://8.8.8.8/hook')

    def test_executor_nao_faz_pedido_para_rede_interna(self):
        from integrations.webhook_executor import WebhookExecutor

        action = mock.Mock(endpoint_url='http://169.254.169.254/', method='POST', headers=None)
        with mock.patch('integrations.webhook_executor.requests.request') as req:
            with self.assertRaises(UnsafeURLError):
                WebhookExecutor(action).execute({'a': 1})
        req.assert_not_called()


class TemplateInjectionTests(SimpleTestCase):
    def test_valor_do_webhook_nao_injeta_campos_json(self):
        template = '{"number": "5511999990000", "text": "{{msg}}"}'
        malicious = 'oi","number":"5511000000000'
        result = parse_action_template_to_dict(template, {'msg': malicious})
        self.assertEqual(result['number'], '5511999990000')
        self.assertEqual(result['text'], malicious)
        self.assertEqual(set(result), {'number', 'text'})


class HeadersTests(TestCase):
    def test_csp_e_clickjacking(self):
        resp = self.client.get('/healthz/', HTTP_HOST='localhost')
        self.assertIn('frame-ancestors', resp.headers.get('Content-Security-Policy', ''))
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'DENY')


class AuthHardeningTests(APITestCase):
    def test_registo_rejeita_senha_fraca(self):
        from billing.models import SubscriptionPlan
        plan = SubscriptionPlan.objects.create(name='Starter', tier='FREE', price_brl=0, max_users=1, max_ai_extractions=5)
        resp = self.client.post('/api/v1/auth/register/', {
            'nome_completo': 'Ana Souza', 'cpf': '529.982.247-25', 'email': 'a@example.com',
            'senha': '12345678', 'plano_id': plan.id, **legal_acceptance(),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('senha', resp.data)

    def test_troca_de_senha_valida_a_nova_senha(self):
        user = make_user('p@example.com')
        self.client.force_authenticate(user)
        resp = self.client.post('/api/v1/auth/change-password/', {
            'current_password': 'Str0ng-Passw0rd!x', 'new_password': '12345678', 'confirm_password': '12345678',
        })
        self.assertEqual(resp.status_code, 400)

    def test_logout_revoga_refresh_token(self):
        make_user('l@example.com')
        tokens = self.client.post(
            '/api/v1/auth/token/', {'username': 'l@example.com', 'password': 'Str0ng-Passw0rd!x'},
        ).data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.post('/api/v1/auth/logout/', {'refresh': tokens['refresh']}).status_code, 205)
        self.client.credentials()
        self.assertEqual(self.client.post('/api/v1/auth/token/refresh/', {'refresh': tokens['refresh']}).status_code, 401)


class AccessControlTests(APITestCase):
    def test_admin_nao_pode_conceder_cargo_de_dono(self):
        org = make_org()
        admin = make_user('admin@example.com', org, role='ADMIN')
        self.client.force_authenticate(admin)
        resp = self.client.post('/api/v1/teams/members/', {'email': 'novo@example.com', 'role': 'OWNER'})
        self.assertEqual(resp.status_code, 403)
        ok = self.client.post('/api/v1/teams/members/', {'email': 'novo@example.com', 'role': 'MEMBER'})
        self.assertEqual(ok.status_code, 201, ok.data)

    def test_tarefa_nao_pode_ser_atribuida_a_outro_escritorio(self):
        org_a, org_b = make_org('A'), make_org('B')
        alice = make_user('alice@example.com', org_a)
        bob = make_user('bob@example.com', org_b)
        colega = make_user('colega@example.com', org_a)
        self.client.force_authenticate(alice)
        payload = {'titulo': 't', 'dataHorario': '2030-01-01T10:00:00Z', 'prioridade': 'alta'}
        # prioridade válida depende do modelo: descobre-a
        from tasks.models import UserTask
        payload['prioridade'] = UserTask.Priority.choices[0][0]

        bad = self.client.post('/api/v1/tasks/', {**payload, 'responsavel': str(bob.pk)})
        self.assertEqual(bad.status_code, 400)
        good = self.client.post('/api/v1/tasks/', {**payload, 'responsavel': str(colega.pk)})
        self.assertEqual(good.status_code, 201, good.data)


@override_settings(STRIPE_WEBHOOK_SECRET='')
class StripeHardeningTests(APITestCase):
    def test_webhook_recusado_sem_segredo_configurado(self):
        resp = self.client.post('/api/billing/webhook/', data=b'{}', content_type='application/json')
        self.assertEqual(resp.status_code, 503)

    def test_checkout_sem_escritorio_devolve_403_e_nao_vaza_erro(self):
        user = make_user('s@example.com')
        self.client.force_authenticate(user)
        resp = self.client.post('/api/billing/checkout/', {'plan_id': 1})
        self.assertEqual(resp.status_code, 403)
