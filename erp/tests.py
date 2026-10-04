from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from cadrius.tests_security import make_org, make_user
from erp import engine
from erp.models import ErpCallLog, ErpConnector


def fake_response(status=200, body=b'{"id": 7}'):
    return mock.Mock(status_code=status, raw=mock.Mock(read=lambda n, decode_content=True: body))


@override_settings(OUTBOUND_ALLOW_PRIVATE_NETWORKS=False)
class ErpTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('o@x.com', self.org, role='OWNER')
        self.viewer = make_user('v@x.com', self.org, role='VIEWER')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        p = mock.patch('erp.engine.validate_outbound_url', side_effect=lambda u, **k: u)
        p.start()
        self.addCleanup(p.stop)

    def _create(self, **extra):
        body = {'name': 'Projuris', 'preset': 'PROJURIS', 'base_url': 'https://acme.projuris.com.br/api', 'token': 'segredo-123', **extra}
        return self.client.post('/api/v1/erp/connectors/', body, format='json')

    def test_create_hides_secret_encrypts_and_starts_dry_run_only(self):
        r = self._create()
        self.assertEqual(r.status_code, 201)
        self.assertNotIn('segredo-123', r.content.decode())
        self.assertTrue(r.json()['has_credentials'])
        self.assertFalse(r.json()['live_enabled'])
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT credentials FROM erp_erpconnector')
            self.assertNotIn('segredo-123', cur.fetchone()[0])
        self.assertEqual(self._create().status_code, 409)

    def test_rejects_http_and_bad_operation_paths_and_non_admin(self):
        self.assertEqual(self._create(name='h', base_url='http://acme.com/api').status_code, 400)
        bad = {'x_op': {'method': 'GET', 'path': 'https://evil.com/x'}}
        self.assertEqual(self._create(name='b', operations=bad).status_code, 400)
        member = APIClient()
        member.force_authenticate(make_user('m@x.com', self.org, role='MEMBER'))
        self.assertEqual(member.post('/api/v1/erp/connectors/', {}, format='json').status_code, 403)

    def test_dry_run_builds_request_without_network(self):
        cid = self._create().json()['id']
        with mock.patch('erp.engine.requests.request') as net:
            r = self.client.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'criar_tarefa', 'data': {'titulo': 'Ligar ao cliente'}}, format='json')
            net.assert_not_called()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['dry_run'])
        self.assertEqual(r.json()['request']['json'], {'titulo': 'Ligar ao cliente'})
        self.assertNotIn('segredo', r.content.decode())
        self.assertTrue(ErpCallLog.objects.get().dry_run)

    def test_missing_required_and_unknown_operation(self):
        cid = self._create().json()['id']
        self.assertEqual(self.client.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'criar_tarefa', 'data': {}}, format='json').json()['code'], 'missing_fields')
        self.assertEqual(self.client.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'nada'}, format='json').json()['code'], 'unknown_operation')

    def test_live_needs_enable_then_confirmation(self):
        cid = self._create().json()['id']
        run = lambda **kw: self.client.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'criar_tarefa', 'data': {'titulo': 'T'}, 'dry_run': False, **kw}, format='json')
        self.assertEqual(run().json()['code'], 'live_disabled')
        self.client.patch(f'/api/v1/erp/connectors/{cid}/', {'live_enabled': True}, format='json')
        self.assertEqual(run().json()['code'], 'needs_confirmation')
        with mock.patch('erp.engine.requests.request', return_value=fake_response(201)) as net:
            r = run(confirm=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status_code'], 201)
        kwargs = net.call_args.kwargs
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer segredo-123')

    def test_read_operation_live_without_confirmation_and_viewer_blocked(self):
        cid = self._create().json()['id']
        self.client.patch(f'/api/v1/erp/connectors/{cid}/', {'live_enabled': True}, format='json')
        with mock.patch('erp.engine.requests.request', return_value=fake_response(200)):
            r = self.client.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'buscar_processo', 'data': {'cnj': '1'}, 'dry_run': False}, format='json')
        self.assertEqual(r.status_code, 200)
        v = APIClient()
        v.force_authenticate(self.viewer)
        self.assertEqual(v.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'ping', 'dry_run': False}, format='json').status_code, 403)

    def test_redirect_and_unreachable_are_errors_and_other_org_isolated(self):
        cid = self._create().json()['id']
        self.client.patch(f'/api/v1/erp/connectors/{cid}/', {'live_enabled': True}, format='json')
        with mock.patch('erp.engine.requests.request', return_value=fake_response(302, b'')):
            r = self.client.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'ping', 'dry_run': False}, format='json')
        self.assertEqual(r.json()['code'], 'redirect')
        other = APIClient()
        other.force_authenticate(make_user('z@z.com', make_org(), role='OWNER'))
        self.assertEqual(other.post(f'/api/v1/erp/connectors/{cid}/run/', {'operation': 'ping'}, format='json').status_code, 404)

    def test_path_param_is_url_encoded_and_cannot_change_host(self):
        c = ErpConnector.objects.create(organization=self.org, name='c', preset='PROJURIS', base_url='https://acme.com/api')
        req = engine.build_request(c, 'registrar_andamento', {'processo_id': '../../x?y=1', 'texto': 't'})
        self.assertEqual(req['url'], 'https://acme.com/api/v1/processos/..%2F..%2Fx%3Fy%3D1/andamentos')
