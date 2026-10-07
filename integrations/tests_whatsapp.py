"""CAD-225: WhatsApp hospedado pelo Cadrius — conectar com QR/código, link para o celular e conexão usada pelas automações."""
from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from automations.messaging import whatsapp_connection
from cadrius.tests_security import make_org, make_user
from integrations import whatsapp_hosted as wa


class FakeEvolution:
    def __init__(self):
        self.state = 'inexistente'
        self.calls = []

    def __call__(self, method, path, **kw):
        self.calls.append((method, path, kw))
        if path == '/':
            return 200, {}
        if path.startswith('/instance/connectionState/'):
            return (404, {}) if self.state == 'inexistente' else (200, {'instance': {'state': self.state}})
        if path == '/instance/create':
            self.state = 'close'
            return 201, {}
        if path.startswith('/instance/connect/'):
            self.state = 'connecting'
            return 200, {'base64': 'data:image/png;base64,AAA', 'pairingCode': 'ABCD1234'}
        if path.startswith('/instance/logout/') or path.startswith('/instance/delete/'):
            self.state = 'inexistente'
            return 200, {}
        return 404, {}


@override_settings(EVOLUTION_API_BASE_URL='http://evolution:8080', EVOLUTION_API_GLOBAL_KEY='k', FRONTEND_URL='https://app.example.com')
class WhatsAppHostedTests(APITestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('m@x.com', self.org, role='MEMBER')
        self.evo = FakeEvolution()
        patcher = mock.patch.object(wa, '_call', side_effect=self.evo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_numero_brasileiro_normalizado_e_invalido_recusado(self):
        self.assertEqual(wa.normalize_number('(11) 98888-7777'), '5511988887777')
        self.assertEqual(wa.normalize_number('+55 21 3333-4444'), '552133334444')
        with self.assertRaises(wa.WhatsAppError):
            wa.normalize_number('123')

    def test_conectar_devolve_qr_e_codigo_e_so_gestor(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post('/api/v1/integrations/whatsapp/conectar/', {'numero': '11988887777'}).status_code, 403)
        self.client.force_authenticate(self.owner)
        r = self.client.post('/api/v1/integrations/whatsapp/conectar/', {'numero': '11988887777'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['codigo_pareamento'], 'ABCD1234')
        self.assertTrue(r.data['qrcode'].startswith('data:image'))
        create = next(c for c in self.evo.calls if c[1] == '/instance/create')
        self.assertEqual(create[2]['json']['instanceName'], wa.instance_name(self.org))
        self.assertIsNone(whatsapp_connection(self.org))                      # ainda não conectou

    def test_quando_conecta_vira_conexao_das_automacoes_e_desconectar_desativa(self):
        self.client.force_authenticate(self.owner)
        self.client.post('/api/v1/integrations/whatsapp/conectar/', {'numero': '11988887777'}, format='json')
        self.evo.state = 'open'
        st = self.client.get('/api/v1/integrations/whatsapp/').data
        self.assertTrue(st['conectado'])
        conn = whatsapp_connection(self.org)
        self.assertEqual(conn.credentials, {'hosted': True, 'instance_name': wa.instance_name(self.org)})   # sem chave global
        self.assertEqual(self.client.post('/api/v1/integrations/whatsapp/desconectar/').status_code, 204)
        self.assertIsNone(whatsapp_connection(self.org))

    def test_conexao_do_escritorio_vence_conexao_manual_mais_nova(self):
        """CAD-229: uma conexão manual criada depois (teste, nome de instância errado) não desvia os envios."""
        from integrations.models import AppConnection
        self.client.force_authenticate(self.owner)
        self.client.post('/api/v1/integrations/whatsapp/conectar/', {'numero': '11988887777'}, format='json')
        self.evo.state = 'open'
        self.client.get('/api/v1/integrations/whatsapp/')
        hosted = whatsapp_connection(self.org)
        AppConnection.objects.create(user=self.owner, name='manual', app_name='WHATSAPP',
                                     credentials={'instance_name': 'inventada', 'api_key': 'x'})
        self.assertEqual(whatsapp_connection(self.org).pk, hosted.pk)

    def test_envio_recusado_vira_motivo_legivel(self):
        from integrations.evolution import WhatsAppEvolutionExecutor, WhatsAppSendError
        cases = [
            (400, {'response': {'message': [{'exists': False, 'number': '5511988887777'}]}}, 'não tem WhatsApp'),
            (404, {'response': {'message': ['The "x" instance does not exist']}}, 'não está conectado'),
            (401, {'error': 'Unauthorized'}, 'chave de acesso'),
            (500, {'response': {'message': ['Connection Closed']}}, 'desconectado'),
        ]
        for code, body, expected in cases:
            resp = mock.Mock(status_code=code, json=lambda b=body: b)
            with mock.patch('integrations.evolution.requests.post', return_value=resp):
                with self.assertRaises(WhatsAppSendError) as ctx:
                    WhatsAppEvolutionExecutor(base_url='http://evolution:8080', api_key='k').send(
                        'cadrius-x', {'number': '5511988887777', 'text': 'oi'})
            self.assertIn(expected, str(ctx.exception))

    def test_link_publico_mostra_codigo_sem_login_e_expira(self):
        self.client.force_authenticate(self.owner)
        link = self.client.post('/api/v1/integrations/whatsapp/link/', {'numero': '11988887777'}, format='json').data['link']
        self.assertTrue(link.startswith('https://app.example.com/whatsapp/'))
        token = link.rsplit('/', 1)[1]
        self.client.force_authenticate(None)
        r = self.client.get(f'/api/v1/publico/whatsapp/{token}/')
        self.assertEqual((r.status_code, r.data['codigo_pareamento']), (200, 'ABCD1234'))
        self.assertEqual(self.client.get('/api/v1/publico/whatsapp/forjado/').status_code, 400)
        with mock.patch('integrations.whatsapp_hosted.LINK_MAX_AGE', -1):
            self.assertIn('expirou', self.client.get(f'/api/v1/publico/whatsapp/{token}/').data['detail'])

    @override_settings(EVOLUTION_API_GLOBAL_KEY='')
    def test_sem_servidor_hospedado_tela_mostra_indisponivel(self):
        self.client.force_authenticate(self.owner)
        self.assertFalse(self.client.get('/api/v1/integrations/whatsapp/').data['disponivel'])
