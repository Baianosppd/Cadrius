from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core import signing
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from gcal import google_api as g
from gcal.models import GoogleCalendarApp, GoogleCalendarLink, TaskEventMap
from gcal import sync
from tasks.models import UserTask

CLIENT_ID = '123-abc.apps.googleusercontent.com'


def run_now(func, *args):
    """Executa a "fila" na hora (o Django-Q não roda nos testes)."""
    module, name = func.rsplit('.', 1)
    return getattr(__import__(module, fromlist=[name]), name)(*args)


class Base(TestCase):
    def setUp(self):
        cache.clear()   # o token de acesso fica em cache por conexão
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.app = GoogleCalendarApp.objects.create(organization=self.org, client_id=CLIENT_ID, client_secret='segredo-do-escritorio')
        self.link = GoogleCalendarLink.objects.create(user=self.owner, app=self.app, refresh_token='refresh-1')
        self.calls = []
        self.events = {}
        p1 = mock.patch('gcal.signals._enqueue', side_effect=run_now)
        p2 = mock.patch('gcal.google_api.refresh_access_token', return_value=('at-1', 3600))
        p3 = mock.patch('gcal.google_api.calendar_call', side_effect=self.fake_calendar)
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def fake_calendar(self, token, method, path, params=None, json=None):
        self.calls.append((method, path, json, params))
        if method == 'POST':
            eid = f'ev{len(self.events) + 1}'
            self.events[eid] = json
            return {'id': eid}
        eid = path.rsplit('/', 1)[-1]
        if method == 'PATCH':
            if eid not in self.events:
                raise g.GoogleNotFound(path)
            self.events[eid] = json
            return {'id': eid}
        if method == 'DELETE':
            if eid not in self.events:
                raise g.GoogleNotFound(path)
            del self.events[eid]
            return {}
        return {'items': [], 'nextSyncToken': 'sync-1'}

    def task(self, **kw):
        defaults = dict(titulo='Prazo recurso', descricao='Proc. 0001', scheduled_at=timezone.now() + timedelta(days=1),
                        priority='alta', responsavel=self.owner, sincronizar=True)
        defaults.update(kw)
        return UserTask.objects.create(**defaults)


class PushTests(Base):
    def test_criar_tarefa_cria_evento_com_marcador_e_cor(self):
        task = self.task()
        method, path, body, _ = self.calls[0]
        self.assertEqual((method, path), ('POST', '/calendars/primary/events'))
        self.assertEqual(body['summary'], 'Prazo recurso')
        self.assertEqual(body['colorId'], '11')
        self.assertEqual(body['extendedProperties']['private']['cadrius_task_id'], str(task.pk))
        self.assertEqual(TaskEventMap.objects.get(task=task).event_id, 'ev1')

    def test_editar_atualiza_o_mesmo_evento_e_concluir_marca_feito(self):
        task = self.task()
        task.titulo = 'Prazo recurso (novo)'
        task.save()
        task.completed = True
        task.save()
        self.assertEqual([c[0] for c in self.calls], ['POST', 'PATCH', 'PATCH'])
        self.assertEqual(self.calls[1][1], '/calendars/primary/events/ev1')
        self.assertEqual(len(self.events), 1)                                   # sem duplicar
        self.assertEqual(self.events['ev1']['summary'], '✔ Prazo recurso (novo)')
        self.assertEqual(self.events['ev1']['transparency'], 'transparent')

    def test_desligar_sincronizacao_remove_o_evento_e_excluir_tarefa_tambem(self):
        task = self.task()
        task.sincronizar = False
        task.save()
        self.assertEqual(self.events, {})
        self.assertFalse(TaskEventMap.objects.exists())
        other = self.task(titulo='Outra')
        self.assertEqual(len(self.events), 1)
        with self.captureOnCommitCallbacks(execute=True):
            other.delete()
        self.assertEqual(self.events, {})

    def test_privacidade_sem_detalhes(self):
        self.app.share_details = False
        self.app.save()
        self.task()
        body = self.calls[0][2]
        self.assertEqual(body['summary'], 'Tarefa Cadrius')
        self.assertNotIn('description', body)

    def test_sem_conexao_ou_sem_flag_nao_chama_o_google(self):
        self.task(sincronizar=False)
        outro = make_user('m@example.com', self.org)
        self.task(responsavel=outro)
        self.assertEqual(self.calls, [])

    def test_evento_apagado_no_google_e_recriado(self):
        task = self.task()
        self.events.clear()
        task.titulo = 'X'
        task.save()
        self.assertEqual([c[0] for c in self.calls], ['POST', 'PATCH', 'POST'])

    def test_token_revogado_marca_reconexao_e_para_de_tentar(self):
        with mock.patch('gcal.google_api.refresh_access_token', side_effect=g.GoogleAuthError('invalid_grant')):
            self.task()
        self.link.refresh_from_db()
        self.assertEqual(self.link.status, 'needs_reauth')
        self.assertTrue(AuditEvent.objects.filter(action='connection.updated').exists())
        before = len(self.calls)
        self.task(titulo='Depois')
        self.assertEqual(len(self.calls), before)


class PullTests(Base):
    def setUp(self):
        super().setUp()
        self.task_obj = self.task()
        self.mapping = TaskEventMap.objects.get(task=self.task_obj)
        self.calls.clear()

    def pull(self, items, next_sync='sync-2'):
        with mock.patch('gcal.google_api.calendar_call', return_value={'items': items, 'nextSyncToken': next_sync}):
            return sync.pull_link(GoogleCalendarLink.objects.select_related('app', 'user').get(pk=self.link.pk))

    def event(self, **kw):
        base = {'id': 'ev1', 'status': 'confirmed', 'summary': 'Prazo recurso', 'updated': (timezone.now() + timedelta(minutes=5)).isoformat(),
                'start': {'dateTime': self.task_obj.scheduled_at.isoformat()},
                'extendedProperties': {'private': {'cadrius_task_id': str(self.task_obj.pk), 'cadrius': '1'}}}
        base.update(kw)
        return base

    def test_mudar_horario_e_titulo_no_google_atualiza_a_tarefa(self):
        new_start = timezone.now() + timedelta(days=3)
        res = self.pull([self.event(summary='✔ Prazo remarcado', start={'dateTime': new_start.isoformat()})])
        self.assertEqual(res['updated'], 1)
        self.task_obj.refresh_from_db()
        self.assertEqual(self.task_obj.titulo, 'Prazo remarcado')                      # prefixo "feito" não vaza para o título
        self.assertEqual(self.task_obj.scheduled_at.replace(microsecond=0), new_start.replace(microsecond=0))
        self.link.refresh_from_db()
        self.assertEqual(self.link.sync_token, 'sync-2')
        self.assertEqual(self.calls, [])                                                # update() não dispara o sinal: sem eco de volta

    def test_eco_da_nossa_gravacao_e_ignorado(self):
        old = (self.mapping.last_synced_at - timedelta(minutes=1)).isoformat()
        res = self.pull([self.event(summary='Alterado por engano', updated=old)])
        self.assertEqual(res['updated'], 0)
        self.task_obj.refresh_from_db()
        self.assertEqual(self.task_obj.titulo, 'Prazo recurso')

    def test_evento_apagado_no_google_desliga_a_sincronizacao_mas_mantem_a_tarefa(self):
        res = self.pull([self.event(status='cancelled')])
        self.assertEqual(res['unsynced'], 1)
        self.task_obj.refresh_from_db()
        self.assertFalse(self.task_obj.sincronizar)
        self.assertFalse(TaskEventMap.objects.exists())

    def test_ignora_eventos_que_nao_sao_do_cadrius_ou_de_outra_tarefa(self):
        res = self.pull([self.event(id='zzz'), self.event(extendedProperties={'private': {'cadrius_task_id': '999'}})])
        self.assertEqual(res, {'updated': 0, 'unsynced': 0})

    def test_sync_token_invalido_recomeca_do_zero(self):
        self.link.sync_token = 'velho'
        self.link.save()
        answers = [g.GoogleNotFound('410'), {'items': [], 'nextSyncToken': 'novo'}]

        def fake(token, method, path, params=None, json=None):
            r = answers.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch('gcal.google_api.calendar_call', side_effect=fake):
            sync.pull_link(GoogleCalendarLink.objects.select_related('app', 'user').get(pk=self.link.pk))
        self.link.refresh_from_db()
        self.assertEqual(self.link.sync_token, 'novo')

    def test_pull_all_conta_conexoes_e_erros(self):
        with mock.patch('gcal.sync.pull_link', side_effect=g.GoogleRetryable('429')):
            self.assertEqual(sync.pull_all()['errors'], 1)
        with mock.patch('gcal.sync.pull_link', return_value={'updated': 2, 'unsynced': 1}):
            self.assertEqual(sync.pull_all(), {'links': 1, 'updated': 2, 'unsynced': 1, 'errors': 0, 'eventos': 0})


@override_settings(FRONTEND_URL='https://app.example.com', API_PUBLIC_URL='https://api.example.com')
class ApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.member = make_user('m@example.com', self.org, role='MEMBER')
        self.base = '/api/v1/integrations/google-calendar/'

    def configure(self):
        self.client.force_authenticate(self.owner)
        return self.client.put(self.base + 'app/', {'client_id': CLIENT_ID, 'client_secret': 'segredo-xyz'}, format='json')

    def test_so_gestor_configura_o_app_e_o_segredo_nunca_volta_e_fica_cifrado(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.put(self.base + 'app/', {'client_id': CLIENT_ID, 'client_secret': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.configure().status_code, 200)
        status_ = self.client.get(self.base).data
        self.assertTrue(status_['app_configured'])
        self.assertNotIn('segredo', str(status_))
        self.assertEqual(status_['redirect_uri'], 'https://api.example.com/api/v1/integrations/google-calendar/callback/')
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT client_secret FROM gcal_googlecalendarapp')
            self.assertTrue(cur.fetchone()[0].startswith('enc::'))
        # atualizar sem reenviar o segredo mantém o anterior
        self.client.put(self.base + 'app/', {'client_id': CLIENT_ID, 'event_minutes': 60}, format='json')
        self.assertEqual(GoogleCalendarApp.objects.get().client_secret, 'segredo-xyz')

    def test_client_id_invalido_e_segredo_obrigatorio_na_primeira_vez(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.put(self.base + 'app/', {'client_id': 'abc', 'client_secret': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.client.put(self.base + 'app/', {'client_id': CLIENT_ID}, format='json').status_code, 400)

    def test_conectar_sem_app_configurado_e_recusado(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(self.base + 'connect/').status_code, 400)

    def connect(self):
        self.configure()
        self.client.force_authenticate(self.member)
        resp = self.client.post(self.base + 'connect/')
        self.assertEqual(resp.status_code, 200)
        return parse_qs(urlparse(resp.data['authorization_url']).query), resp

    def test_fluxo_completo_conecta_e_guarda_o_refresh_token_cifrado(self):
        q, resp = self.connect()
        self.assertEqual(q['client_id'], [CLIENT_ID])                       # usa o app DO ESCRITÓRIO
        self.assertEqual(q['scope'], [g.SCOPE])
        self.assertEqual((q['access_type'], q['code_challenge_method']), (['offline'], ['S256']))
        self.assertEqual(q['redirect_uri'], ['https://api.example.com/api/v1/integrations/google-calendar/callback/'])
        from django.core.cache import cache
        from gcal.api import _pending_key
        nonce = signing.loads(q['state'][0], salt='cadrius.gcal')['n']
        verifier = cache.get(_pending_key(nonce))['v']
        self.client.force_authenticate(None)
        self.client.cookies.clear()                   # CAD-225: não depende de cookie (o navegador descartava)
        with mock.patch('gcal.google_api.exchange_code', return_value={'refresh_token': 'rt-1', 'access_token': 'a'}) as ex:
            cb = self.client.get(self.base + 'callback/', {'state': q['state'][0], 'code': 'abc'})
        self.assertEqual(cb['Location'], 'https://app.example.com/integracoes?gcal=ok')
        self.assertEqual(ex.call_args.args[0:2], (CLIENT_ID, 'segredo-xyz'))
        self.assertEqual(ex.call_args.args[4], verifier)
        link = GoogleCalendarLink.objects.get(user=self.member)
        self.assertEqual((link.refresh_token, link.status), ('rt-1', 'active'))
        self.assertTrue(AuditEvent.objects.filter(action='connection.created').exists())

    def test_callback_recusa_state_invalido_negado_e_sem_refresh_token(self):
        self.client.force_authenticate(None)

        def callback(params):
            return self.client.get(self.base + 'callback/', params)['Location']

        def fresh():                                  # o state é de uso único: cada tentativa começa uma conexão nova
            q, _ = self.connect()
            self.client.force_authenticate(None)
            return {'state': q['state'][0], 'code': 'x'}

        self.assertTrue(callback({'state': 'forjado', 'code': 'x'}).endswith('gcal=state_invalid'))
        self.assertTrue(callback({'error': 'access_denied'}).endswith('gcal=denied'))
        with mock.patch('gcal.google_api.exchange_code', return_value={'access_token': 'a'}):
            self.assertTrue(callback(fresh()).endswith('gcal=no_refresh_token'))
        with mock.patch('gcal.google_api.exchange_code', side_effect=g.GoogleAuthError('x')):
            self.assertTrue(callback(fresh()).endswith('gcal=code_rejected'))
        with mock.patch('gcal.google_api.exchange_code', side_effect=g.GoogleAuthError('x', code='redirect_uri_mismatch')):
            self.assertTrue(callback(fresh()).endswith('gcal=redirect_mismatch'))
        used = fresh()
        with mock.patch('gcal.google_api.exchange_code', return_value={'access_token': 'a'}):
            callback(used)
        self.assertTrue(callback(used).endswith('gcal=state_invalid'))          # repetir o mesmo retorno é recusado
        self.assertFalse(GoogleCalendarLink.objects.exists())

    def test_desconectar_revoga_e_apaga_e_remover_o_app_desconecta_todos(self):
        self.configure()
        app = GoogleCalendarApp.objects.get()
        GoogleCalendarLink.objects.create(user=self.member, app=app, refresh_token='rt-m')
        self.client.force_authenticate(self.member)
        with mock.patch('gcal.google_api.revoke') as revoke:
            self.assertEqual(self.client.post(self.base + 'disconnect/').status_code, 204)
            revoke.assert_called_once_with('rt-m')
        self.assertFalse(GoogleCalendarLink.objects.exists())
        GoogleCalendarLink.objects.create(user=self.member, app=app, refresh_token='rt-m2')
        self.client.force_authenticate(self.owner)
        with mock.patch('gcal.google_api.revoke'):
            self.assertEqual(self.client.delete(self.base + 'app/').status_code, 204)
        self.assertFalse(GoogleCalendarApp.objects.exists() or GoogleCalendarLink.objects.exists())
