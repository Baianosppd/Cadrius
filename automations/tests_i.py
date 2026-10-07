"""CAD-223: captação, pesquisa de satisfação, gatilhos novos (diários e por evento), suspensão de prazos, parametrização,
conformidade das automações, integrações novas e CNPJ pela BrasilAPI."""
from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from automations import catalog, engine, governance
from automations.models import Rule, RuleRun
from automations.templates import TEMPLATES
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact

NEW_TEMPLATES = ('lead_responder', 'pesquisa_contrato_concluido', 'detrator_ligar', 'nota_enviar_cliente', 'custas_reembolso',
                 'suspensao_prazos_equipe', 'aniversario_cliente', 'funil_parado', 'processo_parado', 'meta_mes_equipe')


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.maria = Contact.objects.create(organization=self.org, name='Maria Cliente', email='maria@c.com', phone='11999998888',
                                            email_consent=True, whatsapp_consent=True, birthday='03-06')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        on_commit = mock.patch('django.db.transaction.on_commit', side_effect=lambda fn: fn())
        on_commit.start()
        self.addCleanup(on_commit.stop)
        bh = mock.patch('automations.messaging.business_hours', return_value=True)
        bh.start()
        self.addCleanup(bh.stop)

    def rule(self, key, **kw):
        t = dict(TEMPLATES[key])
        kw.setdefault('enabled', True)
        kw.setdefault('require_approval', False)
        return Rule.objects.create(organization=self.org, **{**catalog.clean_rule(t), 'name': t['name'], **kw})


class CatalogTests(Base):
    def test_25_gatilhos_e_modelos_novos_simulam(self):
        self.assertEqual(len(catalog.TRIGGERS), 26)   # +1 no CAD-226 (atalho)
        for key in NEW_TEMPLATES:
            out = engine.simulate(self.rule(key, enabled=False))
            self.assertIn('passos', out, key)

    def test_pesquisa_so_com_cliente_no_gatilho(self):
        with self.assertRaises(catalog.RuleError):
            catalog.clean_actions('monthly_goal', [{'type': 'send_survey', 'params': {'mensagem': 'oi'}}])


class LeadAndSurveyTests(Base):
    def form(self, **extra):
        res = self.c.post('/api/v1/marketing/formularios/', {'titulo': 'Fale com o escritório', 'assuntos': ['Previdenciário'], **extra},
                          format='json')
        self.assertEqual(res.status_code, 201, res.data)
        return res.data

    def test_formulario_publico_vira_contato_oportunidade_e_gatilho(self):
        f = self.form()
        self.rule('lead_responder')
        pub = APIClient()
        self.assertEqual(pub.get(f'/api/v1/publico/captacao/{f["token"]}/').data['titulo'], 'Fale com o escritório')
        sem_consent = pub.post(f'/api/v1/publico/captacao/{f["token"]}/', {'nome': 'João', 'email': 'joao@x.com'}, format='json')
        self.assertEqual(sem_consent.status_code, 400)
        with mock.patch('core.queue.enqueue', side_effect=lambda fn, *a: engine.execute(*a)):
            ok = pub.post(f'/api/v1/publico/captacao/{f["token"]}/', {'nome': 'João Silva', 'email': 'joao@x.com', 'assunto': 'Previdenciário',
                                                                      'consentimento': True, 'aceita_email': True}, format='json')
        self.assertEqual(ok.status_code, 201, ok.data)
        c = Contact.objects.get(source='form')
        self.assertEqual((c.source, c.email_consent, c.whatsapp_consent), ('form', True, False))
        from carteira.models import Opportunity
        self.assertEqual(Opportunity.objects.get(contact=c).area, 'Previdenciário')
        from tasks.models import UserTask
        self.assertTrue(UserTask.objects.filter(titulo__startswith='Responder João Silva').exists())
        robo = pub.post(f'/api/v1/publico/captacao/{f["token"]}/', {'nome': 'Bot', 'email': 'b@x.com', 'consentimento': True,
                                                                    'site': 'http://spam'}, format='json')
        self.assertEqual(robo.status_code, 201)
        self.assertEqual(Contact.objects.filter(source='form').count(), 1)

    def test_formulario_com_texto_de_captacao_e_barrado(self):
        res = self.c.post('/api/v1/marketing/formularios/', {'titulo': 'Consulta grátis — contrate já', 'assuntos': []}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('OAB', res.data['detail'])

    def test_pesquisa_enviada_respondida_e_detrator_vira_tarefa(self):
        from marketing import leads
        from tasks.models import UserTask
        sv = leads.create_survey(self.org, self.maria, 'Contrato concluído')
        self.assertEqual(leads.create_survey(self.org, self.maria).pk, sv.pk)            # não duplica pesquisa aberta
        self.rule('detrator_ligar')
        pub = APIClient()
        self.assertIn('recomendaria', pub.get(f'/api/v1/publico/pesquisa/{sv.token}/').data['pergunta'])
        self.assertEqual(pub.post(f'/api/v1/publico/pesquisa/{sv.token}/', {'nota': 11}, format='json').status_code, 400)
        with mock.patch('core.queue.enqueue', side_effect=lambda fn, *a: engine.execute(*a)):
            ok = pub.post(f'/api/v1/publico/pesquisa/{sv.token}/', {'nota': 4, 'comentario': 'Demorou'}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(pub.post(f'/api/v1/publico/pesquisa/{sv.token}/', {'nota': 9}, format='json').status_code, 400)
        self.assertTrue(UserTask.objects.filter(titulo__startswith='Ligar para Maria Cliente').exists())
        res = self.c.get('/api/v1/marketing/resultados/').data
        self.assertEqual(res['satisfacao']['nps'], -100)

    def test_acao_pedir_avaliacao_envia_link(self):
        from carteira.models import FeeAgreement, Receivable
        ag = FeeAgreement.objects.create(organization=self.org, contact=self.maria, title='Assessoria', kind='mensal', total_cents=100000)
        Receivable.objects.create(organization=self.org, agreement=ag, contact=self.maria, description='Última', amount_cents=100000,
                                  due_date=timezone.localdate() + timedelta(days=1))
        self.rule('pesquisa_contrato_concluido')
        now = timezone.localtime().replace(hour=10)
        with mock.patch('integrations.email_layout.send', return_value='escritorio') as send:
            out = engine.tick(now=now)
        self.assertEqual(out['diarios'], 1)
        self.assertIn('/pesquisa/', send.call_args.args[2])


class DailyTriggerTests(Base):
    def test_aniversario_oportunidade_parada_processo_parado_e_meta(self):
        from carteira.models import FinanceSettings, Opportunity
        from research.models import MonitoredCase
        today = date(2030, 3, 6)
        now = timezone.make_aware(timezone.datetime(2030, 3, 6, 10, 0))
        opp = Opportunity.objects.create(organization=self.org, contact=self.maria, title='Revisional')
        Opportunity.objects.filter(pk=opp.pk).update(stage_changed_at=now - timedelta(days=10))
        case = MonitoredCase.objects.create(organization=self.org, cnj='0001234-56.2030.8.26.0100', tribunal='tjsp')
        MonitoredCase.objects.filter(pk=case.pk).update(last_movement_at=now - timedelta(days=90))
        cfg = FinanceSettings.of(self.org)
        cfg.monthly_goal_cents = 1000000
        cfg.save()
        for key, tc in (('funil_parado', None), ('processo_parado', None), ('meta_mes_equipe', {'dia': today.day})):
            self.rule(key, **({'trigger_config': tc} if tc else {}))
        self.rule('aniversario_cliente')
        with mock.patch('integrations.email_layout.send', return_value='escritorio') as send, \
                mock.patch('django.utils.timezone.localdate', return_value=today):
            out = engine.tick(now=now)
            again = engine.tick(now=now)
        self.assertEqual(out['diarios'], 4)
        self.assertEqual(again['diarios'], 0)                                          # uma vez por evento
        self.assertIn('aniversário', send.call_args.args[2])

    def test_despesa_lancada_dispara(self):
        from carteira import services
        with mock.patch('automations.engine.emit') as emit:
            services.create_expense(self.org, self.owner, description='Custas', category='custas', amount_cents=3000,
                                    when=timezone.localdate(), contact=self.maria, reimbursable=True)
        self.assertEqual(emit.call_args.args[1], 'expense_created')


class CourtTests(Base):
    def test_suspensao_cadastrada_pela_cadrius_avisa_e_entra_no_prazo(self):
        from django.contrib.auth import get_user_model

        from forense.calendar import Calendar
        from research.models import MonitoredCase
        MonitoredCase.objects.create(organization=self.org, cnj='0001234-56.2030.8.26.0100', tribunal='tjsp')
        staff = get_user_model().objects.create_user(username='jur@cadrius.com', email='jur@cadrius.com', password='x-Str0ng-Pass!',
                                                     is_staff=True, is_superuser=True)
        sc = APIClient()
        sc.force_authenticate(staff)
        self.rule('suspensao_prazos_equipe')
        body = {'tribunal': 'tjsp', 'tipo': 'prazos', 'inicio': '2030-03-11', 'fim': '2030-03-12', 'motivo': 'Portaria 99/2030 — migração',
                'fonte': 'https://www.tjsp.jus.br/portaria-99'}
        with mock.patch('accounts.mfa.staff_session_ok', return_value=True), \
                mock.patch('notifications.services.notify') as notify, \
                mock.patch('core.queue.enqueue', side_effect=lambda fn, *a: engine.execute(*a)):
            bad = sc.post('/api/v1/backoffice/forense/suspensoes/', {**body, 'fonte': 'http://x'}, format='json')
            res = sc.post('/api/v1/backoffice/forense/suspensoes/', body, format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['escritorios_avisados'], 1)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(len(self.c.get('/api/v1/forense/suspensoes/').data), 0)       # fora da janela de hoje±
        cal = Calendar(self.org, 'tjsp')
        self.assertIn('Suspensão de prazos', cal.reason(date(2030, 3, 11)))
        self.assertIsNone(Calendar(self.org, 'tjrj').reason(date(2030, 3, 11)))
        self.assertEqual(cal.count(date(2030, 3, 8), 1)['vencimento'], date(2030, 3, 13))   # sexta + 1 útil pula 11 e 12


class CustomizationTests(Base):
    def test_fluxo_pedido_proposta_aprovacao_entrega(self):
        from django.contrib.auth import get_user_model
        member = make_user('adv@x.com', self.org, role='MEMBER')
        mc = APIClient()
        mc.force_authenticate(member)
        self.assertEqual(mc.post('/api/v1/support/parametrizacoes/', {'area': 'automacao', 'objetivo': 'curto'}, format='json').status_code, 400)
        res = mc.post('/api/v1/support/parametrizacoes/', {'area': 'automacao', 'objetivo': 'Quando chegar sentença, criar tarefa de '
                                                           'recurso e avisar o cliente.', 'frequencia': 'toda sentença'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        pk = res.data['id']
        staff = get_user_model().objects.create_user(username='sup@cadrius.com', email='sup@cadrius.com', password='x-Str0ng-Pass!',
                                                     is_staff=True, is_superuser=True)
        sc = APIClient()
        sc.force_authenticate(staff)
        with mock.patch('accounts.mfa.staff_session_ok', return_value=True):
            skip = sc.patch(f'/api/v1/backoffice/support/parametrizacoes/{pk}/', {'etapa': 'em_execucao'}, format='json')
            sc.patch(f'/api/v1/backoffice/support/parametrizacoes/{pk}/', {'etapa': 'em_analise'}, format='json')
            prop = sc.patch(f'/api/v1/backoffice/support/parametrizacoes/{pk}/', {'etapa': 'proposta', 'proposta': 'Regra com gatilho de '
                            'publicação, condição "sentença" e duas ações.', 'prazo_dias': 3}, format='json')
        self.assertEqual(skip.status_code, 400)
        self.assertEqual(prop.status_code, 200, prop.data)
        self.assertEqual(mc.post(f'/api/v1/support/parametrizacoes/{pk}/aprovar/').status_code, 403)   # membro não aprova
        ok = self.c.post(f'/api/v1/support/parametrizacoes/{pk}/aprovar/')
        self.assertEqual(ok.data['etapa'], 'aprovado')
        with mock.patch('accounts.mfa.staff_session_ok', return_value=True):
            sc.patch(f'/api/v1/backoffice/support/parametrizacoes/{pk}/', {'etapa': 'em_execucao'}, format='json')
            done = sc.patch(f'/api/v1/backoffice/support/parametrizacoes/{pk}/', {'etapa': 'entregue'}, format='json')
        self.assertEqual(done.data['etapa'], 'entregue')
        ticket = self.c.get('/api/v1/support/tickets/').data[0]
        self.assertEqual(ticket['parametrizacao']['etapa'], 'entregue')


class GovernanceTests(Base):
    def test_aponta_mensagem_sem_aprovacao_e_texto_problematico(self):
        t = dict(TEMPLATES['pagamento_agradecimento'])
        t['actions'][0]['params'] = {**t['actions'][0]['params'], 'mensagem': 'Resultado garantido! Indique e ganhe desconto.'}
        Rule.objects.create(organization=self.org, name='Ruim', require_approval=False, enabled=True, **{
            k: v for k, v in catalog.clean_rule(t).items() if k != 'name'})
        rep = self.c.get('/api/v1/automations/conformidade/').data
        regras = [a['regra'] for a in rep['regras'][0]['achados']]
        self.assertIn('Mensagem ao cliente sem aprovação', regras)
        self.assertTrue(any(r.startswith('Texto:') for r in regras))
        self.assertLess(rep['nota'], 100)
        self.assertEqual(governance.platform_overview()['regras_cliente_sem_aprovacao'], 1)


class IntegrationTests(Base):
    def test_catalogo_e_testes_de_conexao(self):
        from integrations import services
        from integrations.catalog import CATALOG
        for app in ('JUDIT', 'AUTENTIQUE', 'NFEIO', 'OMIE', 'BREVO', 'MAILCHIMP', 'RDSTATION', 'ZOOM', 'ZENVIA', 'BRASILAPI'):
            self.assertIn(app, CATALOG)
        conn = mock.Mock(app_name='MAILCHIMP', credentials={'api_key': 'abc'})
        with self.assertRaises(services.IntegrationError):
            services.test_connection(conn)
        resp = mock.Mock(status_code=200, json=lambda: {'companyName': 'Silva Adv'})
        with mock.patch('integrations.services.requests.get', return_value=resp) as get:
            msg = services.test_connection(mock.Mock(app_name='BREVO', credentials={'api_key': 'k'}))
        self.assertIn('Silva Adv', msg)
        self.assertEqual(get.call_args.kwargs['headers']['api-key'], 'k')

    def test_cnpj_pela_brasilapi(self):
        resp = mock.Mock(status_code=200, json=lambda: {'razao_social': 'SILVA ADVOGADOS', 'descricao_situacao_cadastral': 'ATIVA',
                                                        'ddd_telefone_1': '1133334444', 'municipio': 'SAO PAULO', 'uf': 'SP'})
        with mock.patch('integrations.public_data.requests.get', return_value=resp) as get:
            ok = self.c.get('/api/v1/contacts/cnpj/11222333000181/')
            self.c.get('/api/v1/contacts/cnpj/11222333000181/')                          # cache
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual((ok.data['razao_social'], ok.data['telefone']), ('SILVA ADVOGADOS', '1133334444'))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(self.c.get('/api/v1/contacts/cnpj/123/').status_code, 400)

    def test_aniversario_guarda_so_dia_e_mes(self):
        res = self.c.post('/api/v1/contacts/', {'name': 'Ana', 'birthday': '06/03/1980'}, format='json')
        self.assertEqual(res.data['birthday'], '03-06')
        self.assertEqual(self.c.post('/api/v1/contacts/', {'name': 'Bia', 'birthday': '31/02'}, format='json').status_code, 400)


class RunStatusSanity(Base):
    def test_nada_executa_sem_regra(self):
        self.assertEqual(RuleRun.objects.count(), 0)
