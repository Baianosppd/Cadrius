from datetime import datetime, timedelta
from unittest import mock

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from automations.models import Rule
from brain import profile, suggestions
from brain.models import AIFeedback, AutomationSuggestion, OfficeProfile
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from research.models import CaseMovement, MonitoredCase
from tasks.models import UserTask


class SuggestionTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def weekly_tasks(self, title='Relatório semanal para o cliente', n=5):
        start = timezone.make_aware(datetime(2026, 8, 3, 9))               # segunda
        for i in range(n):
            t = UserTask.objects.create(titulo=f'{title} {i + 1:02d}/08', responsavel=self.member, scheduled_at=start + timedelta(weeks=i))
            UserTask.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=5 * i))

    def test_normaliza_titulo(self):
        self.assertEqual(suggestions.normalize_title('Relatório semanal 12/03 - Cliente Ávila 2026'), 'relatorio semanal cliente avila')

    def test_tarefa_recorrente_vira_regra_semanal_e_aceitar_cria_regra_desligada(self):
        self.weekly_tasks()
        created = suggestions.refresh(self.org)
        self.assertEqual(len(created), 1)
        s = created[0]
        self.assertTrue(s.key.startswith('recorrente:'))
        self.assertIn('segunda', s.title)
        res = self.c.get('/api/v1/brain/suggestions/').json()
        self.assertEqual(len(res['abertas']), 1)
        res = self.c.post(f'/api/v1/brain/suggestions/{s.pk}/accept/')
        self.assertEqual(res.status_code, 200, res.content)
        rule = Rule.objects.get(pk=res.json()['regra_id'])
        self.assertEqual((rule.trigger, rule.enabled, rule.trigger_config['dia_semana']), ('schedule', False, 0))
        self.assertEqual(self.c.post(f'/api/v1/brain/suggestions/{s.pk}/accept/').status_code, 409)
        self.assertTrue(AIFeedback.objects.filter(action_kind='automation_suggestion', decision='approved').exists())
        self.assertEqual(suggestions.refresh(self.org), [])                 # aceita: não volta

    def test_modelos_e_dispensa_com_soneca(self):
        client = Contact.objects.create(organization=self.org, name='Maria', phone='11988887777', whatsapp_consent=True)
        case = MonitoredCase.objects.create(organization=self.org, cnj='0000832-35.2018.4.01.3202', tribunal='trf1', client=client)
        for i in range(6):
            CaseMovement.objects.create(case=case, digest=f'd{i}', name='Juntada', notified=True)
        keys = {s.key for s in suggestions.refresh(self.org)}
        self.assertEqual(keys, {'template:andamento_cria_tarefa', 'template:andamento_avisa_cliente'})
        s = AutomationSuggestion.objects.get(key='template:andamento_avisa_cliente')
        self.c.force_authenticate(self.member)
        self.assertEqual(self.c.post(f'/api/v1/brain/suggestions/{s.pk}/dismiss/').status_code, 403)
        self.c.force_authenticate(self.owner)
        self.assertEqual(self.c.post(f'/api/v1/brain/suggestions/{s.pk}/dismiss/').json()['status'], 'dismissed')
        self.assertEqual({x.key for x in suggestions.refresh(self.org)}, set())    # dispensada não volta em 60 dias
        AutomationSuggestion.objects.filter(pk=s.pk).update(decided_at=timezone.now() - timedelta(days=61))
        self.assertEqual([x.key for x in suggestions.refresh(self.org)], ['template:andamento_avisa_cliente'])
        Rule.objects.create(organization=self.org, name='x', trigger='case_movement', enabled=True,
                            actions=[{'type': 'create_task', 'params': {}}])
        suggestions.refresh(self.org)
        self.assertFalse(AutomationSuggestion.objects.filter(key='template:andamento_cria_tarefa', status='open').exists())  # já tem regra

    def test_isolamento(self):
        self.weekly_tasks()
        s = suggestions.refresh(self.org)[0]
        other = APIClient()
        other.force_authenticate(make_user('o@y.com', make_org('Outro'), role='OWNER'))
        self.assertEqual(other.post(f'/api/v1/brain/suggestions/{s.pk}/accept/').status_code, 404)
        self.assertEqual(other.get('/api/v1/brain/suggestions/').json()['abertas'], [])


class ProfileTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def test_perfil_calculado_editavel_e_no_prompt(self):
        MonitoredCase.objects.create(organization=self.org, cnj='0000832-35.2018.4.01.3202', tribunal='trt2')
        res = self.c.get('/api/v1/brain/profile/').json()
        self.assertEqual(res['calculado']['tribunais'][0]['nome'], 'TRT2')
        self.assertIn('trabalhista', res['calculado']['areas_sugeridas'])
        self.assertEqual(res['areas'], ['trabalhista'])                     # sugerida vira padrão enquanto vazio
        res = self.c.put('/api/v1/brain/profile/', {'areas': ['trabalhista', 'previdenciario'], 'tom': 'didatico', 'cidade': 'Recife',
                                                    'assinatura': 'Dra. Ana — OAB/PE 123'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.c.put('/api/v1/brain/profile/', {'areas': ['astrologia']}, format='json').status_code, 400)
        ctx = profile.prompt_context(self.org)
        self.assertIn('Previdenciário', ctx)
        self.assertIn('didático', ctx)
        self.c.force_authenticate(self.member)
        self.assertEqual(self.c.put('/api/v1/brain/profile/', {'tom': 'formal'}, format='json').status_code, 403)

    def test_insights(self):
        AIFeedback.objects.create(organization=self.org, action_kind='document_extraction', decision='approved')
        AIFeedback.objects.create(organization=self.org, action_kind='document_extraction', decision='edited')
        AIFeedback.objects.create(organization=self.org, action_kind='document_extraction', decision='rejected')
        res = self.c.get('/api/v1/brain/insights/').json()
        k = res['por_tipo']['document_extraction']
        self.assertEqual((k['total'], k['taxa_aceite'], k['taxa_sem_edicao']), (3, 67, 33))
        self.assertEqual(res['tempo_economizado_min'], 12)

    def test_minuta_usa_assinatura_e_aprende_ao_revisar(self):
        from brain.models import MemoryItem
        OfficeProfile.objects.create(organization=self.org, signature='Dra. Ana Lima\nOAB/PE 123')
        from minutas.models import DraftTemplate
        t = DraftTemplate.objects.create(organization=self.org, name='Carta', body='Atenciosamente,\n{{assinatura}}')
        d = self.c.post('/api/v1/minutas/', {'modelo': f'org:{t.pk}'}, format='json').json()
        self.assertIn('OAB/PE 123', d['conteudo'])
        self.c.patch(f'/api/v1/minutas/{d["id"]}/', {'conteudo': d['conteudo'] + '\nP.S.', 'status': 'revisada'}, format='json')
        self.assertTrue(AIFeedback.objects.filter(action_kind='draft', decision='edited').exists())
        self.assertTrue(MemoryItem.objects.filter(kind='draft_example', source=f'draft:{d["id"]}').exists())
        with mock.patch('brain.memory.similar', return_value=[(0.9, MemoryItem.objects.get(kind='draft_example'))]):
            from minutas.services import _prompt
            self.assertIn('Exemplo de minuta já revisada', _prompt(self.org, 'base'))


class VocabularyTests(APITestCase):
    """Vocabulário do escritório: trocas repetidas de termos viram regra proposta; aprovada, vale no prompt e no texto."""

    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def test_detecta_trocas_e_ignora_nomes_numeros_e_pontuacao(self):
        from brain import style
        out = style.term_changes('O requerente João Silva pagou R$ 500 ao cliente.',
                                 'O autor José Souza pagou R$ 700 ao constituinte!')
        pairs = {(c['from'], c['to']) for c in out}
        self.assertIn(('cliente', 'constituinte'), pairs)
        self.assertNotIn(('joão silva', 'josé souza'), pairs)
        self.assertFalse(any(c['from'].isdigit() or c['to'].isdigit() for c in out))
        self.assertEqual(style.term_changes('Vossa Senhoria decidirá', 'Vossa Excelência decidirá')[0]['to'], 'excelência')
        self.assertEqual(style.term_changes('', 'x'), [])

    def test_aprende_propoe_aprova_e_aplica(self):
        from brain import style
        from brain.models import OfficeRule
        from minutas.models import DraftTemplate
        t = DraftTemplate.objects.create(organization=self.org, name='Peça', body='Requer o requerente a citação do réu.')
        for i in range(3):
            d = self.c.post('/api/v1/minutas/', {'modelo': f'org:{t.pk}'}, format='json').json()
            novo = d['conteudo'].replace('o requerente', 'a parte autora')
            self.c.patch(f'/api/v1/minutas/{d["id"]}/', {'conteudo': novo, 'status': 'revisada'}, format='json')
        self.assertEqual(style.mine_terms(self.org, min_evidence=4), [])          # 3 textos < 4 exigidos
        created = style.mine_terms(self.org)
        self.assertEqual([(r.from_value, r.to_value, r.evidence) for r in created], [('o requerente', 'a parte autora', 3)])
        rule = created[0]
        self.assertIn('em vez de "o requerente"', rule.describe())
        d = self.c.post('/api/v1/minutas/', {'modelo': f'org:{t.pk}'}, format='json').json()
        self.assertIn('o requerente', d['conteudo'])                               # proposta ainda não vale
        res = self.c.get('/api/v1/brain/approvals/').json()
        self.assertIn(rule.pk, [r['id'] for r in res['rules_proposed']])
        self.assertEqual(self.c.post(f'/api/v1/brain/rules/{rule.pk}/decide/', {'decision': 'approve'}, format='json').status_code, 200)
        d = self.c.post('/api/v1/minutas/', {'modelo': f'org:{t.pk}'}, format='json').json()
        self.assertEqual(d['conteudo'], 'Requer a parte autora a citação do réu.')
        self.assertIn('Vocabulário do escritório aplicado (1 troca(s))', d['aviso'])
        self.assertIn('escreva "a parte autora" em vez de "o requerente"', profile.prompt_context(self.org))
        self.assertEqual(style.apply_terms(self.org, 'O REQUERENTE e O requerente')[0], 'A PARTE AUTORA e A parte autora')
        piece = self.c.post('/api/v1/marketing/conteudos/', {'canal': 'blog', 'tema': 'Quando o requerente perde o prazo', 'usar_ia': False},
                            format='json').json()
        self.assertNotIn('o requerente', piece['texto'].lower())
        other = make_org('Outro')
        self.assertEqual(style.apply_terms(other, 'o requerente')[0], 'o requerente')      # isolado por escritório
        rule.refresh_from_db()
        self.assertEqual(rule.status, OfficeRule.Status.ACTIVE)
        self.assertFalse(OfficeRule.objects.filter(organization=self.org, kind='field_correction').exists())
