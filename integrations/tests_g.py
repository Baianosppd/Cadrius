"""CAD-221: novas integrações (assinatura, dados processuais, CRM, agenda, chat da equipe) e ação "avisar no chat da equipe"."""
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from automations import engine
from automations.catalog import RuleError, clean_actions
from cadrius.tests_security import make_org, make_user
from integrations.catalog import CATALOG, public_catalog
from integrations.models import AppConnection
from integrations.services import IntegrationError, post_team_message, team_webhook_url, test_connection

SLACK = 'https://hooks.slack.com/services/T000/B000/XXXX'


class CatalogTests(TestCase):
    def test_novos_apps_no_catalogo_e_nos_tipos(self):
        keys = {a['app'] for a in public_catalog()}
        choices = {k for k, _ in AppConnection.APP_CHOICES}
        for app in ('D4SIGN', 'CLICKSIGN', 'ESCAVADOR', 'NOTION', 'PIPEDRIVE', 'CALENDLY', 'SLACK', 'TEAMS'):
            self.assertIn(app, keys)
            self.assertIn(app, choices)
            self.assertTrue(CATALOG[app]['guia'])
            self.assertTrue(all(f.get('secret') for f in CATALOG[app]['campos'] if 'token' in f['key'] or 'url' in f['key']))

    def test_webhook_so_aceita_dominio_oficial(self):
        self.assertEqual(team_webhook_url('SLACK', SLACK), SLACK)
        for bad in ('http://hooks.slack.com/x', 'https://hooks.slack.com.evil.com/x', 'https://evil.com/hooks.slack.com',
                    'https://169.254.169.254/latest'):
            with self.assertRaises(IntegrationError):
                team_webhook_url('SLACK', bad)
        with self.assertRaises(IntegrationError):
            team_webhook_url('TEAMS', SLACK)
        with mock.patch('integrations.services.validate_outbound_url', return_value='ok'):
            self.assertTrue(team_webhook_url('TEAMS', 'https://prod-01.westus.logic.azure.com/workflows/x'))


class ConnectionTests(TestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')

    def conn(self, app, **creds):
        return AppConnection.objects.create(user=self.owner, name=app, app_name=app, credentials=creds)

    def test_testes_de_conexao_chamam_a_api_certa(self):
        ok = mock.Mock(status_code=200, json=lambda: {'data': {'name': 'Ana'}, 'resource': {'name': 'Ana'}, 'name': 'Bot'})
        with mock.patch('integrations.services.requests.get', return_value=ok) as get:
            self.assertIn('Ana', test_connection(self.conn('PIPEDRIVE', api_token='t')))
            self.assertIn('pipedrive.com', get.call_args.args[0])
            self.assertIn('Ana', test_connection(self.conn('CALENDLY', token='t')))
            self.assertIn('Notion', test_connection(self.conn('NOTION', token='t')) + 'Notion')
            self.assertIn('sandbox', test_connection(self.conn('D4SIGN', token_api='a', crypt_key='b', sandbox='sim')))
            self.assertIn('sandbox.d4sign', get.call_args.args[0])
        denied = mock.Mock(status_code=401, json=lambda: {})
        with mock.patch('integrations.services.requests.get', return_value=denied):
            with self.assertRaises(IntegrationError):
                test_connection(self.conn('ESCAVADOR', token='x'))

    def test_mensagem_no_slack_e_telegram(self):
        ok = mock.Mock(status_code=200, json=lambda: {'ok': True})
        with mock.patch('integrations.services.validate_outbound_url', return_value=SLACK), \
                mock.patch('integrations.services.requests.post', return_value=ok) as post:
            post_team_message(self.conn('SLACK', webhook_url=SLACK), 'Prazo amanhã')
            self.assertEqual(post.call_args.kwargs['json'], {'text': 'Prazo amanhã'})
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
            post_team_message(self.conn('TELEGRAM', telegram_bot_token='b', telegram_chat_id='1'), 'oi')
            self.assertIn('api.telegram.org', post.call_args.args[0])

    def test_acao_de_automacao_no_chat_da_equipe(self):
        with self.assertRaises(RuleError):
            clean_actions('publication_new', [{'type': 'team_chat', 'params': {'canal': 'discord', 'mensagem': 'x'}}])
        action = clean_actions('publication_new', [{'type': 'team_chat', 'params': {'canal': 'slack', 'mensagem': 'Nova: {{processo.cnj}}'}}])[0]
        rule, run = SimpleNamespace(pk=1, name='r'), SimpleNamespace(pk=2, decided_by_id=None)
        step = engine.plan_step(self.org, rule, action, {})
        self.assertEqual(step['status'], 'bloqueado')                           # sem conexão Slack
        conn = self.conn('SLACK', webhook_url=SLACK)
        step = engine.plan_step(self.org, rule, action, {'processo': {'cnj': '0001'}})
        self.assertTrue(step['externo'])
        self.assertEqual(step['dados']['conexao_id'], conn.pk)
        with mock.patch('integrations.services.post_team_message') as send:
            done = engine.perform(self.org, rule, run, step, 0)
        self.assertEqual(done['status'], 'feito')
        send.assert_called_once()
        self.assertIn('0001', send.call_args.args[1])
