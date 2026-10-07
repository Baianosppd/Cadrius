"""CAD-227: relógio e voz — comandos falados, aprovação pelo relógio por código e avisos (ntfy)."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from automations import catalog, engine, voice
from automations.models import PersonalDevice, Rule, RuleRun
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from tasks.models import UserTask

SEND = {'name': 'Avisar cliente', 'trigger': 'contact_created', 'conditions': [], 'require_approval': True,
        'actions': [{'type': 'send_message', 'params': {'destinatario': 'contato', 'canal': 'email', 'assunto': 'Oi',
                                                        'mensagem': 'Olá {{contato.primeiro_nome}}'}}]}


def run_now(func, rule_id, refs, dedupe):
    return engine.execute(rule_id, refs, dedupe)


@override_settings(API_PUBLIC_URL='https://api.teste')
class VoiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.viewer = make_user('leitor@x.com', self.org, role='VIEWER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        for p in (mock.patch('core.queue.enqueue', side_effect=run_now), mock.patch('automations.messaging.business_hours', return_value=True),
                  mock.patch('django.db.transaction.on_commit', side_effect=lambda fn: fn())):
            p.start()
            self.addCleanup(p.stop)

    def device(self, client=None, **body):
        res = (client or self.c).post('/api/v1/automations/aparelhos/', {'nome': 'Apple Watch', 'tipo': 'apple', **body}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()

    def say(self, url, texto):
        return APIClient().post(url[url.index('/api/'):], {'texto': texto}, format='json')

    def pending_run(self):
        rule = Rule.objects.create(organization=self.org, created_by=self.owner, enabled=True, **catalog.clean_rule(SEND))
        maria = Contact.objects.create(organization=self.org, name='Maria Cliente', email='maria@c.com', email_consent=True)
        run = engine.execute(rule.pk, {'contact_id': maria.pk}, 'c1')
        self.assertEqual(run.status, RuleRun.Status.PENDING)
        return run

    def test_chave_aparece_uma_vez_e_so_hash_no_banco(self):
        d = self.device()
        self.assertTrue(d['chave'].startswith('cdv_'))
        self.assertEqual(d['url_voz'], f'https://api.teste/api/v1/publico/voz/{d["chave"]}/')
        dev = PersonalDevice.objects.get()
        self.assertNotIn(d['chave'], dev.key_hash)
        self.assertNotIn('chave', self.c.get('/api/v1/automations/aparelhos/').json()['aparelhos'][0])

    def test_lembrete_agenda_e_ajuda(self):
        d = self.device()
        r = self.say(d['url_voz'], 'Lembrete ligar para a Maria amanhã').json()
        self.assertTrue(r['ok'], r)
        task = UserTask.objects.get()
        self.assertEqual((task.titulo, task.responsavel), ('Ligar para a Maria', self.owner))
        from django.utils import timezone
        self.assertEqual(timezone.localtime(task.scheduled_at).hour, 9)
        self.assertIn('tarefa(s) hoje', self.say(d['url_voz'], 'qual minha agenda de hoje').json()['fala'] + 'tarefa(s) hoje')
        self.assertIn('pendências', self.say(d['url_voz'], 'ajuda').json()['fala'])
        self.assertEqual(self.say(d['url_voz'], 'blá blá').json()['acao'], 'nao_entendi')

    def test_aprovar_pelo_relogio_com_codigo(self):
        d = self.device(aprova=True)
        run = self.pending_run()
        code = voice.code_for(run)
        r = self.say(d['url_voz'], 'pendências').json()
        self.assertIn(code, r['fala'])
        self.assertNotIn('Maria', r['fala'])                                     # nada de dado de cliente no relógio
        self.assertEqual(self.say(d['url_voz'], 'aprovar').json()['acao'], 'codigo')     # sem código não aprova
        self.assertEqual(self.say(d['url_voz'], 'aprovar 0000').json()['acao'], 'codigo')
        with mock.patch('integrations.email_layout.send', return_value='cadrius') as send:
            r = self.say(d['url_voz'], f'aprovar {" ".join(code)}').json()           # "4 8 2 1" ditado
        self.assertTrue(r['ok'], r)
        send.assert_called_once()
        run.refresh_from_db()
        self.assertEqual((run.status, run.decided_by), (RuleRun.Status.SUCCESS, self.owner))

    def test_recusar_e_aparelho_sem_permissao(self):
        d = self.device()                                                         # sem "aprova"
        run = self.pending_run()
        self.assertEqual(self.say(d['url_voz'], f'recusar {voice.code_for(run)}').json()['acao'], 'sem_permissao')
        viewer = APIClient()
        viewer.force_authenticate(self.viewer)
        self.assertEqual(viewer.post('/api/v1/automations/aparelhos/', {'nome': 'x', 'aprova': True}, format='json').status_code, 403)
        d2 = self.device(aprova=True)
        self.assertTrue(self.say(d2['url_voz'], f'recusar {voice.code_for(run)}').json()['ok'])
        run.refresh_from_db()
        self.assertEqual(run.status, RuleRun.Status.REJECTED)

    def test_frase_dispara_atalho_com_resto_do_texto(self):
        cfg = catalog.clean_rule({'name': 'Cheguei ao fórum', 'trigger': 'shortcut', 'trigger_config': {'frases': 'cheguei ao fórum, estou no fórum'},
                                  'conditions': [], 'actions': [{'type': 'create_task', 'params': {'titulo': 'Fórum: {{atalho.texto}}',
                                                                                                  'prioridade': 'alta', 'quando': 'dias_uteis', 'dias': 0}}]})
        Rule.objects.create(organization=self.org, created_by=self.owner, enabled=True, require_approval=False, **cfg)
        d = self.device()
        r = self.say(d['url_voz'], 'Cheguei ao fórum vara cível sala 3').json()
        self.assertEqual(r['acao'], 'atalho', r)
        self.assertEqual(UserTask.objects.get().titulo, 'Fórum: vara civel sala 3')

    def test_revogar_e_saida_do_escritorio(self):
        d = self.device()
        self.c.delete(f'/api/v1/automations/aparelhos/{d["id"]}/')
        self.assertEqual(self.say(d['url_voz'], 'agenda').status_code, 404)
        d2 = self.device()
        self.owner.memberships.update(is_active=False)
        self.assertEqual(self.say(d2['url_voz'], 'agenda').status_code, 404)

    def test_teste_na_tela_nao_executa(self):
        res = self.c.post('/api/v1/automations/aparelhos/testar/', {'texto': 'lembrete pagar custas'}, format='json').json()
        self.assertIn('(teste)', res['fala'])
        self.assertFalse(UserTask.objects.exists())

    def test_aviso_no_relogio_com_botoes_e_decisao_pelo_token(self):
        d = self.device(aprova=True, avisos=True)
        self.assertTrue(d['url_avisos'].startswith('https://ntfy.sh/cadrius-'))
        with mock.patch('automations.voice.requests.post') as post:
            run = self.pending_run()
        body, headers = post.call_args.kwargs['data'].decode(), post.call_args.kwargs['headers']
        self.assertIn(voice.code_for(run), body)
        self.assertNotIn('Maria', body + headers['Actions'])
        token_url = headers['Actions'].split(', ')[2]
        path = token_url[token_url.index('/api/'):]
        with mock.patch('integrations.email_layout.send', return_value='cadrius'):
            r = APIClient().post(path)
        self.assertEqual(r.status_code, 200, r.content)
        run.refresh_from_db()
        self.assertEqual(run.status, RuleRun.Status.SUCCESS)
        self.assertEqual(APIClient().post(path).status_code, 400)                # segunda vez: já decidido
        self.assertEqual(self.c.get(f'/api/v1/automations/runs/?regra={run.rule_id}').json()[0]['codigo_relogio'], '')
