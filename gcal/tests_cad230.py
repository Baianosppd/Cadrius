"""CAD-230: Google Agenda com escrita (criar, alterar, cancelar), Planilhas e Documentos, e conexão sem app próprio."""
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from cadrius.tests_security import make_org, make_user
from gcal import google_api as g
from gcal import workspace, write
from gcal.models import ExternalEvent, GoogleCalendarApp, GoogleCalendarLink, GoogleFile
from gcal.platform import CALENDAR, DRIVE_FILE


class FakeGoogle:
    def __init__(self):
        self.calls, self.events, self.n = [], {}, 0

    def __call__(self, token, method, url, params=None, json=None):
        self.calls.append((method, url, json, params))
        self.n += 1
        if url.startswith(g.CAL_BASE):
            eid = url.rsplit('/', 1)[-1]
            if method == 'POST':
                self.events[f'ev{self.n}'] = json
                return {'id': f'ev{self.n}'}
            if method in ('PATCH', 'DELETE'):
                if eid not in self.events:
                    raise g.GoogleNotFound(url)
                if method == 'DELETE':
                    del self.events[eid]
                    return {}
                self.events[eid].update(json)
                return {'id': eid}
            return {'items': [{'id': k, 'status': 'confirmed', **v} for k, v in self.events.items()]}
        if url == f'{g.SHEETS_BASE}/spreadsheets':
            return {'spreadsheetId': f'sheet{self.n}', 'spreadsheetUrl': f'https://docs.google.com/spreadsheets/d/sheet{self.n}/edit'}
        if url.startswith(f'{g.SHEETS_BASE}/spreadsheets/'):
            return {'updates': {'updatedRows': len(json['values'])}}
        if url == f'{g.DOCS_BASE}/documents':
            return {'documentId': f'doc{self.n}abcdef'}
        if url.startswith(f'{g.DOCS_BASE}/documents/'):
            return {}
        raise AssertionError(url)


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.other = make_user('adv@x.com', self.org, role='MEMBER')
        self.app = GoogleCalendarApp.objects.create(organization=self.org, client_id='x.apps.googleusercontent.com', client_secret='s')
        self.link = GoogleCalendarLink.objects.create(user=self.owner, app=self.app, refresh_token='r',
                                                      scopes=f'openid email {CALENDAR} {DRIVE_FILE}')
        self.fake = FakeGoogle()
        for p in (mock.patch('gcal.google_api.refresh_access_token', return_value=('at', 3600)),
                  mock.patch('gcal.google_api.api_call', side_effect=self.fake)):
            p.start()
            self.addCleanup(p.stop)


class CalendarWriteTests(Base):
    def when(self, days=1, hour=10):
        return timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=days), datetime.min.time())) \
            + timedelta(hours=hour)

    def test_criar_alterar_cancelar(self):
        ev = write.create_event(self.owner, self.org, titulo='Reunião com Maria', inicio=self.when(), duracao_min=45,
                                local='Escritório', convidados=['maria@x.com'])
        method, url, body, params = self.fake.calls[-1]
        self.assertEqual((method, params['sendUpdates']), ('POST', 'none'))      # convite só se a pessoa pedir
        self.assertEqual(body['attendees'], [{'email': 'maria@x.com'}])
        self.assertEqual(ev.kind, 'reuniao')
        self.assertTrue(ExternalEvent.objects.filter(pk=ev.pk, cancelled=False).exists())   # já aparece na agenda do Cadrius

        ev = write.update_event(self.owner, self.org, ev.pk, inicio=self.when(days=2, hour=15))
        self.assertEqual(timezone.localtime(ev.start).hour, 15)
        self.assertEqual(int((ev.end - ev.start).total_seconds() // 60), 45)    # mantém a duração
        self.assertEqual(self.fake.calls[-1][0], 'PATCH')

        with self.assertRaises(write.CalendarWriteError):                         # não é dono
            write.cancel_event(self.other, self.org, ev.pk)
        write.cancel_event(self.owner, self.org, ev.pk)
        self.assertTrue(ExternalEvent.objects.get(pk=ev.pk).cancelled)

    def test_validacoes(self):
        with self.assertRaises(write.CalendarWriteError):
            write.create_event(self.other, self.org, titulo='x', inicio=self.when())   # sem Google conectado
        with self.assertRaises(write.CalendarWriteError):
            write.create_event(self.owner, self.org, titulo='x', inicio=self.when(), convidados=['não é e-mail'])
        self.link.status = GoogleCalendarLink.Status.NEEDS_REAUTH
        self.link.save()
        with self.assertRaises(write.CalendarWriteError):
            write.create_event(self.owner, self.org, titulo='x', inicio=self.when())

    def test_pela_api_da_tela(self):
        self.client.force_authenticate(self.owner)
        start = timezone.localtime(self.when()).replace(tzinfo=None).isoformat()
        r = self.client.post('/api/v1/integrations/google-calendar/events/', {'titulo': 'Audiência', 'inicio': start}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['tipo'], 'audiencia')
        r = self.client.patch(f'/api/v1/integrations/google-calendar/events/{r.data["id"]}/', {'titulo': 'Audiência de conciliação'},
                              format='json')
        self.assertEqual(r.data['titulo'], 'Audiência de conciliação')
        self.assertEqual(self.client.delete(f'/api/v1/integrations/google-calendar/events/{r.data["id"]}/').status_code, 204)

    def test_assistente_cria_evento_com_confirmacao(self):
        """O caso do usuário: "crie uma reunião hoje às 10h no Google Agenda" agora vai direto para o Google."""
        from assistant.tools import TOOLS
        ctx = mock.Mock(user=self.owner, org=self.org, role='OWNER', perms=None)
        tool = TOOLS['criar_evento_google']
        self.assertTrue(tool.action)                                              # só executa ao confirmar
        out = tool.run(ctx, titulo='Reunião', data=timezone.localdate().isoformat(), hora='10:00')
        self.assertIn('criado no seu Google Agenda', out['mensagem'])
        ev = ExternalEvent.objects.get(pk=out['id'])
        listed = TOOLS['agenda_google'].run(ctx, dias=1)
        self.assertIn(ev.pk, [e['id'] for e in listed])                          # aparece também quando já passou da hora
        out = TOOLS['alterar_evento_google'].run(ctx, id=ev.pk, hora='11:30')
        self.assertIn('11:30', out['mensagem'])
        out = TOOLS['alterar_evento_google'].run(ctx, id=ev.pk, cancelar=True)
        self.assertIn('cancelado', out['mensagem'])


class WorkspaceTests(Base):
    def test_planilha_reaproveitada_e_valores_seguros(self):
        f = workspace.append_rows(self.owner, 'Honorários', [['Maria', '1.500,00', '=HYPERLINK("x")', '00123']],
                                  ['Cliente', 'Valor', 'Obs', 'Código'])
        create = [c for c in self.fake.calls if c[1].endswith(':append')][0]
        self.assertEqual(create[3]['valueInputOption'], 'RAW')                  # fórmula fica como texto
        self.assertEqual(create[2]['values'][1], ['Maria', 1500.0, '=HYPERLINK("x")', '00123'])
        again = workspace.append_rows(self.owner, 'Honorários', [['João', '10']])
        self.assertEqual(again.pk, f.pk)
        self.assertEqual(GoogleFile.objects.count(), 1)
        self.assertEqual(sum(1 for c in self.fake.calls if c[1] == f'{g.SHEETS_BASE}/spreadsheets'), 1)

    def test_documento(self):
        f = workspace.create_doc(self.owner, 'Plano do caso', 'Linha 1\nLinha 2')
        self.assertTrue(f.url.startswith('https://docs.google.com/document/d/'))
        insert = self.fake.calls[-1][2]['requests'][0]['insertText']
        self.assertEqual(insert['text'], 'Linha 1\nLinha 2')

    def test_conexao_antiga_sem_escopo_pede_reconectar(self):
        self.link.scopes = CALENDAR
        self.link.save()
        with self.assertRaises(workspace.WorkspaceError) as ctx:
            workspace.create_doc(self.owner, 'X', 'y')
        self.assertIn('Reconectar', str(ctx.exception))


@override_settings(GOOGLE_CLIENT_ID='plat.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='plat-secret',
                   API_PUBLIC_URL='https://api.example.com', FRONTEND_URL='https://app.example.com')
class PlatformAppTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.client.force_authenticate(self.owner)

    def test_conectar_sem_o_escritorio_configurar_nada(self):
        st = self.client.get('/api/v1/integrations/google-calendar/').data
        self.assertTrue(st['app_configured'])
        self.assertFalse(st['own_app'])
        url = self.client.post('/api/v1/integrations/google-calendar/connect/').data['authorization_url']
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q['client_id'], ['plat.apps.googleusercontent.com'])
        self.assertIn(DRIVE_FILE, q['scope'][0])
        self.assertIn(CALENDAR, q['scope'][0])
        app = GoogleCalendarApp.objects.get(organization=self.org)
        self.assertTrue(app.uses_platform)
        self.assertEqual(app.client_secret, '')                                    # o segredo da plataforma não vai ao banco
        self.assertEqual(app.credentials(), ('plat.apps.googleusercontent.com', 'plat-secret'))

        state = q['state'][0]
        tokens = {'refresh_token': 'rt', 'scope': f'openid {CALENDAR} {DRIVE_FILE}', 'id_token': ''}
        with mock.patch('gcal.google_api.exchange_code', return_value=tokens) as ex:
            r = self.client.get('/api/v1/integrations/google-calendar/callback/', {'state': state, 'code': 'c'})
        self.assertIn('gcal=ok', r['Location'])
        self.assertEqual(ex.call_args.args[:2], ('plat.apps.googleusercontent.com', 'plat-secret'))
        link = GoogleCalendarLink.objects.get(user=self.owner)
        self.assertTrue(link.has_scope(DRIVE_FILE))
        st = self.client.get('/api/v1/integrations/google-calendar/').data
        self.assertEqual(st['recursos'], {'agenda': True, 'planilhas_documentos': True})

    def test_app_proprio_do_escritorio_tem_prioridade_e_pede_reconexao(self):
        self.client.post('/api/v1/integrations/google-calendar/connect/')
        app = GoogleCalendarApp.objects.get(organization=self.org)
        GoogleCalendarLink.objects.create(user=self.owner, app=app, refresh_token='r')
        r = self.client.put('/api/v1/integrations/google-calendar/app/', {'client_id': 'own.apps.googleusercontent.com'}, format='json')
        self.assertEqual(r.status_code, 400)                                       # trocar de app exige o segredo
        r = self.client.put('/api/v1/integrations/google-calendar/app/', {'client_id': 'own.apps.googleusercontent.com',
                                                                          'client_secret': 'own'}, format='json')
        self.assertEqual(r.status_code, 200)
        app.refresh_from_db()
        self.assertFalse(app.uses_platform)
        self.assertEqual(GoogleCalendarLink.objects.get(user=self.owner).status, 'needs_reauth')

    @override_settings(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET='')
    def test_sem_app_nenhum_explica(self):
        r = self.client.post('/api/v1/integrations/google-calendar/connect/')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.client.get('/api/v1/integrations/google-calendar/').data['app_configured'])
