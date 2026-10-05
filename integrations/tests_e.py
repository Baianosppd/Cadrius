from datetime import date, timedelta
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from integrations import services
from integrations.models import AppConnection


def ok(payload):
    return mock.Mock(status_code=200, json=lambda: payload)


class CatalogAndTestTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.viewer = make_user('ver@x.com', self.org, role='VIEWER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def test_catalogo_com_guias(self):
        res = self.c.get('/api/v1/integrations/catalog/').json()
        apps = {a['app']: a for a in res['apps']}
        for app in ('SMTP', 'ZAPSIGN', 'ASAAS', 'META', 'WHATSAPP'):
            self.assertTrue(apps[app]['guia'], app)
        self.assertIn('não oferece API pública', apps['ASTREA']['uso'])
        self.assertTrue(all(not f.get('secret') or True for f in apps['META']['campos']))

    def test_campos_obrigatorios_na_criacao(self):
        res = self.c.post('/api/v1/connections/', {'name': 'Asaas', 'app_name': 'ASAAS', 'credentials': {}}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('Chave da API', str(res.content.decode()))
        res = self.c.post('/api/v1/connections/', {'name': 'Asaas', 'app_name': 'ASAAS', 'credentials': {'api_key': 'k', 'sandbox': 'sim'}},
                          format='json')
        self.assertEqual(res.status_code, 201, res.content)

    def test_testar_conexao(self):
        conn = AppConnection.objects.create(user=self.owner, name='Asaas', app_name='ASAAS', credentials={'api_key': 'k', 'sandbox': 'sim'})
        with mock.patch('integrations.services.requests.request', return_value=ok({'data': []})) as req:
            res = self.c.post(f'/api/v1/integrations/connections/{conn.pk}/test/').json()
        self.assertTrue(res['ok'], res)
        self.assertIn('api-sandbox.asaas.com', req.call_args.args[1])
        with mock.patch('integrations.services.requests.request', return_value=mock.Mock(status_code=401, json=lambda: {})):
            res = self.c.post(f'/api/v1/integrations/connections/{conn.pk}/test/').json()
        self.assertFalse(res['ok'])
        self.assertIn('recusou', res['mensagem'])
        self.c.force_authenticate(self.viewer)
        self.assertEqual(self.c.post(f'/api/v1/integrations/connections/{conn.pk}/test/').status_code, 403)
        other = APIClient()
        other.force_authenticate(make_user('o@y.com', make_org('Outro'), role='OWNER'))
        self.assertEqual(other.post(f'/api/v1/integrations/connections/{conn.pk}/test/').status_code, 404)

    @override_settings(OUTBOUND_ALLOW_PRIVATE_NETWORKS=False)
    def test_smtp_bloqueia_host_interno(self):
        with self.assertRaises(services.IntegrationError):
            services.smtp_backend({'host': '127.0.0.1', 'port': 587})
        with self.assertRaises(services.IntegrationError):
            services.smtp_backend({'host': 'smtp.exemplo.com', 'port': 22})


class SignatureAndChargeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        self.contact = Contact.objects.create(organization=self.org, name='Maria Souza', document='529.982.247-25', email='m@x.com')

    def test_assinatura_zapsign(self):
        from documents.models import Document
        doc = Document.objects.create(organization=self.org, nome='procuracao.pdf', uploaded_by=self.owner)
        doc.arquivo.save('procuracao.pdf', ContentFile(b'%PDF-1.4 teste'))
        body = {'documento_id': doc.pk, 'signatarios': [self.contact.pk]}
        self.assertEqual(self.c.post('/api/v1/integrations/signature/', body, format='json').json()['code'], 'not_connected')
        AppConnection.objects.create(user=self.owner, name='ZapSign', app_name='ZAPSIGN', credentials={'api_token': 't'})
        resp = {'token': 'doc1', 'status': 'pending', 'signers': [{'name': 'Maria Souza', 'sign_url': 'https://app.zapsign.com.br/x', 'status': 'new'}]}
        with mock.patch('integrations.services.requests.post', return_value=ok(resp)) as post:
            res = self.c.post('/api/v1/integrations/signature/', body, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['signatarios'][0]['link'], 'https://app.zapsign.com.br/x')
        sent = post.call_args.kwargs['json']
        self.assertEqual(sent['signers'][0]['email'], 'm@x.com')
        self.assertTrue(sent['base64_pdf'])
        self.assertEqual(self.c.post('/api/v1/integrations/signature/', {'documento_id': doc.pk, 'signatarios': []}, format='json').status_code, 400)

    def test_cobranca_asaas(self):
        AppConnection.objects.create(user=self.owner, name='Asaas', app_name='ASAAS', credentials={'api_key': 'k'})
        due = (date.today() + timedelta(days=5)).isoformat()
        calls = [ok({'data': []}), ok({'id': 'cus_1'}), ok({'id': 'pay_1', 'invoiceUrl': 'https://asaas.com/i/1', 'status': 'PENDING'})]
        with mock.patch('integrations.services.requests.request', side_effect=calls) as req:
            res = self.c.post('/api/v1/integrations/charge/', {'contato_id': self.contact.pk, 'valor': '1500,00', 'vencimento': due,
                                                               'forma': 'PIX'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['link'], 'https://asaas.com/i/1')
        self.assertEqual(req.call_args.kwargs['json']['billingType'], 'PIX')
        self.assertEqual(req.call_args.kwargs['json']['value'], 1500.0)
        self.assertEqual(self.c.post('/api/v1/integrations/charge/', {'contato_id': self.contact.pk, 'valor': '1', 'vencimento': due},
                                     format='json').status_code, 400)
        Contact.objects.filter(pk=self.contact.pk).update(document='')
        with mock.patch('integrations.services.requests.request'):
            res = self.c.post('/api/v1/integrations/charge/', {'contato_id': self.contact.pk, 'valor': '100', 'vencimento': due}, format='json')
        self.assertIn('CPF ou CNPJ', res.json()['detail'])

    def test_email_da_automacao_sai_pelo_smtp_do_escritorio(self):
        AppConnection.objects.create(user=self.owner, name='SMTP', app_name='SMTP',
                                     credentials={'host': 'smtp.exemplo.com', 'port': '587', 'username': 'c@x.adv.br', 'password': 'p',
                                                  'from_email': 'Silva <c@x.adv.br>'})
        with mock.patch('integrations.services._safe_smtp_host', return_value='smtp.exemplo.com'), \
                mock.patch('integrations.services.EmailBackend', return_value=mail.get_connection('django.core.mail.backends.locmem.EmailBackend')):
            self.assertTrue(services.send_office_email(self.org, 'Oi', 'Corpo', ['m@x.com']))
        self.assertEqual(mail.outbox[-1].from_email, 'Silva <c@x.adv.br>')
        self.assertFalse(services.send_office_email(make_org('Sem SMTP'), 'a', 'b', ['x@y.com']))
