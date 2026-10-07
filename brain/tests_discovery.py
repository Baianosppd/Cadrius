from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

from automations.models import Rule
from brain import discovery, suggestions
from brain.models import AutomationSuggestion
from cadrius.tests_security import make_org, make_user


class DiscoveryTests(APITestCase):
    """CAD-226: "Fale sobre seu processo" → sugestões de automação (com e sem IA)."""

    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def test_temas_do_texto(self):
        self.assertEqual(discovery.topics_from_text('Perco tempo com cobrança de honorários e com prazos das publicações')[:2],
                         ['prazos', 'cobranca'])

    def test_sem_ia_usa_temas_e_cita_o_que_a_pessoa_disse(self):
        with mock.patch.object(discovery, '_ask_ai', return_value=None):
            res = self.c.post('/api/v1/brain/discovery/', {'texto': 'Tenho medo de perder prazo das intimações. '
                                                           'Os clientes ligam toda hora perguntando do processo.',
                                                           'temas': ['cobranca']}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body['origem'], 'temas')
        self.assertIn('prazos', body['temas'])
        self.assertTrue(all(s['chave'].startswith('entrevista:') for s in body['sugestoes']))
        self.assertTrue(any('perder prazo' in s['motivo'] for s in body['sugestoes']))
        self.assertTrue(any(s['modelo'] == 'regua_lembrete' for s in body['sugestoes']))
        # aceitar sugestão de modelo pronto cria a regra desligada (antes dava 500: descrição duplicada)
        tpl = next(s for s in body['sugestoes'] if s['modelo'])
        accepted = self.c.post(f'/api/v1/brain/suggestions/{tpl["id"]}/accept/')
        self.assertEqual(accepted.status_code, 200, accepted.content)
        rule = Rule.objects.get(pk=accepted.json()['regra_id'])
        self.assertEqual((rule.enabled, rule.template_key), (False, tpl['modelo']))
        self.assertTrue(rule.description.startswith('Sugerida pela IA'))
        # os detectores não apagam as sugestões da entrevista
        suggestions.refresh(self.org, notify=False)
        self.assertEqual(AutomationSuggestion.objects.filter(organization=self.org, key__startswith='entrevista:').count(),
                         len(body['sugestoes']))

    def test_com_ia_valida_chaves_e_regra_semanal(self):
        ai = {'modelos': [{'chave': 'prazo_lembrete', 'motivo': 'Você disse que esquece prazos.'}, {'chave': 'inventado', 'motivo': 'x'}],
              'semanais': [{'titulo': 'Relatório para clientes', 'dia_semana': 4, 'hora': 16, 'motivo': 'Toda sexta você manda.'},
                           {'titulo': 'x', 'dia_semana': 9}]}
        with mock.patch.object(discovery, '_ask_ai', return_value=ai):
            res = self.c.post('/api/v1/brain/discovery/', {'texto': 'Esqueço prazos e toda sexta mando relatório aos clientes.'},
                              format='json').json()
        self.assertEqual(res['origem'], 'ia')
        keys = [s['chave'] for s in res['sugestoes']]
        self.assertIn('entrevista:prazo_lembrete', keys)
        self.assertNotIn('entrevista:inventado', keys)
        weekly = [s for s in res['sugestoes'] if s['chave'].startswith('entrevista:semanal:')]
        self.assertEqual(len(weekly), 1)
        accepted = self.c.post(f'/api/v1/brain/suggestions/{weekly[0]["id"]}/accept/').json()
        rule = Rule.objects.get(pk=accepted['regra_id'])
        self.assertEqual((rule.trigger, rule.enabled, rule.trigger_config['dia_semana']), ('schedule', False, 4))

    def test_nao_sugere_modelo_ja_usado_e_permissoes(self):
        Rule.objects.create(organization=self.org, name='x', trigger='case_movement', template_key='andamento_cria_tarefa')
        with mock.patch.object(discovery, '_ask_ai', return_value=None):
            res = self.c.post('/api/v1/brain/discovery/', {'temas': ['andamentos']}, format='json').json()
        self.assertNotIn('entrevista:andamento_cria_tarefa', [s['chave'] for s in res['sugestoes']])
        self.assertEqual(self.c.post('/api/v1/brain/discovery/', {'texto': 'oi'}, format='json').status_code, 400)
        self.c.force_authenticate(self.member)
        self.assertEqual(self.c.post('/api/v1/brain/discovery/', {'temas': ['prazos']}, format='json').status_code, 403)
        self.assertEqual(len(self.c.get('/api/v1/brain/discovery/').json()['temas']), len(discovery.TOPICS))

    def test_ia_resposta_invalida_nao_quebra(self):
        reply = SimpleNamespace(text='não é json')
        with mock.patch('aigov.guard.global_ai_enabled', return_value=True), \
                mock.patch('aigov.llm.candidates', return_value=['CLAUDE']), \
                mock.patch('aigov.llm.chat_with_fallback', return_value=reply):
            out = discovery.discover(self.org, self.owner, 'Muitos prazos e publicações todos os dias no escritório.')
        self.assertEqual(out['origem'], 'temas')
        self.assertTrue(out['sugestoes'])
