from rest_framework.test import APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from integrations.models import AppConnection


class ConnectionApiTests(APITestCase):
    def setUp(self):
        self.org = make_org('Escritório A')
        self.owner = make_user('a@example.com', org=self.org, role='OWNER')
        self.viewer = make_user('v@example.com', org=self.org, role='VIEWER')
        self.other = make_user('o@example.com', org=make_org('Outro'), role='OWNER')

    def test_cria_sem_vazar_credenciais(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.post('/api/v1/connections/', {
            'name': 'Telegram do suporte', 'app_name': 'TELEGRAM', 'credentials': {'token': 'segredo-123'},
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertNotIn('credentials', resp.data)
        self.assertNotIn('segredo-123', str(resp.data))
        self.assertTrue(resp.data['has_credentials'])
        listing = self.client.get('/api/v1/connections/')
        self.assertEqual(len(listing.data), 1)
        self.assertNotIn('segredo-123', str(listing.data))
        self.assertTrue(AuditEvent.objects.filter(action='connection.created').exists())

    def test_viewer_nao_cria_mas_lista(self):
        self.client.force_authenticate(self.owner)
        self.client.post('/api/v1/connections/', {'name': 'X', 'app_name': 'WEBHOOK'}, format='json')
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.post('/api/v1/connections/', {'name': 'Y', 'app_name': 'WEBHOOK'}, format='json').status_code, 403)
        self.assertEqual(len(self.client.get('/api/v1/connections/').data), 1)

    def test_isolamento_entre_escritorios(self):
        self.client.force_authenticate(self.owner)
        self.client.post('/api/v1/connections/', {'name': 'X', 'app_name': 'WEBHOOK'}, format='json')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/connections/').data, [])
        conn = AppConnection.objects.get()
        self.assertEqual(self.client.delete(f'/api/v1/connections/{conn.pk}/').status_code, 404)

    def test_nome_duplicado_e_remocao(self):
        self.client.force_authenticate(self.owner)
        body = {'name': 'Dup', 'app_name': 'WEBHOOK'}
        self.assertEqual(self.client.post('/api/v1/connections/', body, format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/v1/connections/', body, format='json').status_code, 400)
        conn = AppConnection.objects.get()
        self.assertEqual(self.client.delete(f'/api/v1/connections/{conn.pk}/').status_code, 204)
