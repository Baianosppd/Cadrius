from datetime import datetime, timedelta
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from automations import catalog, engine
from automations.models import Rule, RuleRun
from automations.templates import TEMPLATES
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from integrations.models import AppConnection
from research.models import CaseMovement, MonitoredCase
from tasks.models import UserTask

S = RuleRun.Status


def at(y, m, d, h=10):
    return timezone.make_aware(datetime(y, m, d, h, 0))


class CatalogTests(APITestCase):
    def test_todos_os_modelos_sao_validos(self):
        for key, t in TEMPLATES.items():
            catalog.clean_rule(t)                                  # não levanta

    def test_validacao(self):
        base = {'name': 'Regra', 'trigger': 'document_confirmed', 'actions': [{'type': 'notify', 'params': {'titulo': 'a', 'mensagem': 'b'}}]}
        self.assertEqual(catalog.clean_rule(base)['conditions'], [])
        bad = [
            {**base, 'trigger': 'nada'},
            {**base, 'name': 'x'},
            {**base, 'actions': []},
            {**base, 'actions': [{'type': 'send_whatsapp', 'params': {'destinatario': 'cliente', 'mensagem': 'oi'}}]},  # sem contato
            {**base, 'conditions': [{'field': 'cliente.nome', 'op': 'eq', 'value': 'x'}]},
            {**base, 'conditions': [{'field': 'prazo.fatal', 'op': 'regex', 'value': 'x'}]},
            {**base, 'trigger': 'case_movement', 'actions': [{'type': 'create_task', 'params': {'titulo': 't', 'quando': 'prazo'}}]},
            {**base, 'trigger': 'schedule', 'trigger_config': {'frequencia': 'mensal'}},
            {**base, 'actions': [{'type': 'erp_call', 'params': {'conector_id': 1, 'operacao': 'x', 'dados': {'a': 1}}}]},
        ]
        for body in bad:
            with self.assertRaises(catalog.RuleError, msg=str(body)):
                catalog.clean_rule(body)
        cond = catalog.clean_conditions('document_confirmed', [{'field': 'documento.tipo', 'op': 'in', 'value': 'Intimação, Citação'}])
        self.assertEqual(cond[0]['value'], ['Intimação', 'Citação'])

    def test_render_e_condicoes(self):
        ctx = {'cliente': {'nome': 'Maria'}, 'prazo': {'fatal': 'sim'}, 'lista': {'x': 1}}
        self.assertEqual(engine.render('Olá {{ cliente.nome }}, {{nada.aqui}}{{lista}}!', ctx), 'Olá Maria, !')
        self.assertTrue(engine.condition_ok({'field': 'prazo.fatal', 'op': 'eq', 'value': 'SIM'}, ctx))
        self.assertTrue(engine.condition_ok({'field': 'cliente.nome', 'op': 'contains', 'value': 'ari'}, ctx))
        self.assertTrue(engine.condition_ok({'field': 'cliente.cpf', 'op': 'not_exists', 'value': ''}, ctx))
        self.assertFalse(engine.condition_ok({'field': 'cliente.nome', 'op': 'in', 'value': ['Ana', 'João']}, ctx))


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.viewer = make_user('ver@x.com', self.org, role='VIEWER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def rule(self, key, **kw):
        t = {k: v for k, v in TEMPLATES[key].items()}
        kw.setdefault('enabled', True)
        return Rule.objects.create(organization=self.org, **{**catalog.clean_rule(t), 'name': t['name'], **kw})

    def case_with_movement(self, client=None):
        case = MonitoredCase.objects.create(organization=self.org, cnj='0001234-56.2026.8.26.0100', tribunal='tjsp',
                                            responsavel=self.member, client=client)
        CaseMovement.objects.create(case=case, digest='abc123', name='Juntada de petição', occurred_at=at(2026, 3, 2))
        return case, {'case_id': case.pk, 'digests': ['abc123']}

    def client_contact(self, **kw):
        return Contact.objects.create(organization=self.org, name='Maria Clara Souza', phone='11988887777', email='maria@x.com', **kw)


class ApiFlowTests(Base):
    def test_criar_de_modelo_simular_e_ligar(self):
        res = self.c.post('/api/v1/automations/rules/', {'modelo': 'andamento_cria_tarefa'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        rid = res.json()['id']
        self.assertFalse(res.json()['ativa'])
        self.assertEqual(self.c.post(f'/api/v1/automations/rules/{rid}/enable/', {'ativa': True}, format='json').json()['code'],
                         'needs_simulation')
        sim = self.c.post(f'/api/v1/automations/rules/{rid}/simulate/')
        self.assertEqual(sim.status_code, 200)
        self.assertEqual(sim.json()['origem'], 'exemplo')
        self.assertIn('Analisar andamento: Juntada de petição', sim.json()['passos'][0]['detalhe'])
        self.assertEqual(UserTask.objects.count(), 0)                                   # simulação não cria nada
        on = self.c.post(f'/api/v1/automations/rules/{rid}/enable/', {'ativa': True}, format='json')
        self.assertTrue(on.json()['ativa'])
        res = self.c.patch(f'/api/v1/automations/rules/{rid}/', {'name': 'Novo nome'}, format='json')
        self.assertTrue(res.json()['ativa'])                                            # nome não muda a lógica
        res = self.c.patch(f'/api/v1/automations/rules/{rid}/', {'actions': [{'type': 'notify', 'params': {'titulo': 'a', 'mensagem': 'b'}}]},
                           format='json')
        self.assertTrue(res.json()['desligada_para_simular'])
        self.assertFalse(res.json()['ativa'])
        self.assertTrue(AuditEvent.objects.filter(action='automation.rule_enabled').exists())
        self.assertEqual(len(self.c.get('/api/v1/automations/catalog/').json()['gatilhos']), 7)
        self.assertEqual(len(self.c.get('/api/v1/automations/templates/').json()), len(TEMPLATES))

    def test_permissoes_e_isolamento(self):
        rid = self.c.post('/api/v1/automations/rules/', {'modelo': 'prazo_lembrete'}, format='json').json()['id']
        self.c.force_authenticate(self.member)
        self.assertEqual(self.c.get('/api/v1/automations/rules/').status_code, 200)
        self.assertEqual(self.c.post('/api/v1/automations/rules/', {'modelo': 'prazo_lembrete'}, format='json').status_code, 403)
        self.assertEqual(self.c.post(f'/api/v1/automations/rules/{rid}/simulate/').status_code, 403)
        other = make_user('o@y.com', make_org('Outro'), role='OWNER')
        self.c.force_authenticate(other)
        self.assertEqual(self.c.get(f'/api/v1/automations/rules/{rid}/').status_code, 404)
        self.assertEqual(self.c.delete(f'/api/v1/automations/rules/{rid}/').status_code, 404)
        self.assertEqual(self.c.post('/api/v1/automations/rules/', {'modelo': 'inexistente'}, format='json').status_code, 400)

    def test_simulacao_usa_dado_real_quando_existe(self):
        contact = self.client_contact()
        self.case_with_movement(client=contact)
        rule = self.rule('andamento_avisa_cliente', enabled=False)
        sim = self.c.post(f'/api/v1/automations/rules/{rule.pk}/simulate/').json()
        self.assertEqual(sim['origem'], 'real')
        self.assertEqual(sim['passos'][0]['status'], 'bloqueado')                       # sem consentimento de WhatsApp
        self.assertIn('não autorizou', sim['passos'][0]['detalhe'])
        self.assertIn('Olá, Maria!', sim['passos'][0]['dados']['mensagem'])


class EngineTests(Base):
    def test_andamento_cria_tarefa_em_dias_uteis_e_dedupe(self):
        case, refs = self.case_with_movement()
        rule = self.rule('andamento_cria_tarefa')
        with mock.patch('django.utils.timezone.localdate', return_value=datetime(2026, 2, 13).date()):
            run = engine.execute(rule.pk, refs, 'k1')
        self.assertEqual(run.status, S.SUCCESS, run.steps)
        task = UserTask.objects.get()
        self.assertEqual(timezone.localtime(task.scheduled_at).date().isoformat(), '2026-02-19')   # 2 dias úteis, pulando o Carnaval
        self.assertEqual(task.responsavel, self.member)
        self.assertIn('Juntada de petição', task.titulo)
        self.assertIsNone(engine.execute(rule.pk, refs, 'k1'))                           # mesmo evento não roda de novo
        rule.refresh_from_db()
        self.assertEqual(rule.run_count, 1)

    def test_condicao_nao_atendida_pula(self):
        _, refs = self.case_with_movement()
        rule = self.rule('andamento_cria_tarefa', conditions=[{'field': 'processo.tribunal', 'op': 'eq', 'value': 'trf1'}])
        self.assertEqual(engine.execute(rule.pk, refs, 'k').status, S.SKIPPED)
        self.assertEqual(UserTask.objects.count(), 0)

    def test_regra_desligada_ou_de_outro_escritorio_nao_roda(self):
        _, refs = self.case_with_movement()
        rule = self.rule('andamento_cria_tarefa', enabled=False)
        self.assertIsNone(engine.execute(rule.pk, refs, 'k'))
        other_org = make_org('Outro')
        other = Rule.objects.create(organization=other_org, name='x', trigger='case_movement', enabled=True,
                                    actions=[{'type': 'notify', 'params': {'titulo': 'a', 'mensagem': 'b'}}])
        self.assertIsNone(engine.execute(other.pk, refs, 'k'))                         # processo não é do escritório da regra

    def test_whatsapp_com_consentimento_espera_aprovacao_e_envia(self):
        contact = self.client_contact(whatsapp_consent=True)
        _, refs = self.case_with_movement(client=contact)
        AppConnection.objects.create(user=self.owner, name='WhatsApp', app_name='WHATSAPP',
                                     credentials={'base_url': 'https://evo.exemplo.com', 'api_key': 'k', 'instance_name': 'esc1'})
        rule = self.rule('andamento_avisa_cliente')
        run = engine.execute(rule.pk, refs, 'k')
        self.assertEqual(run.status, S.PENDING)
        self.assertEqual(run.steps[0]['status'], 'aguardando')
        url = f'/api/v1/automations/runs/{run.pk}/approve/'
        self.c.force_authenticate(self.viewer)
        self.assertEqual(self.c.post(url).status_code, 403)
        self.c.force_authenticate(self.member)
        self.assertEqual(len(self.c.get('/api/v1/automations/runs/', {'status': 'pending_approval'}).json()), 1)
        with mock.patch('integrations.evolution.WhatsAppEvolutionExecutor.send', return_value={'ok': True}) as send:
            res = self.c.post(url)
            self.assertEqual(res.status_code, 200, res.content)
            self.assertEqual(res.json()['status'], S.SUCCESS)
            instance, payload = send.call_args.args
            self.assertEqual((instance, payload['number']), ('esc1', '5511988887777'))
            self.assertIn('Maria', payload['text'])
            self.assertEqual(self.c.post(url).status_code, 409)                         # não envia duas vezes
        self.assertTrue(AuditEvent.objects.filter(action='message.sent').exists())
        self.assertTrue(AuditEvent.objects.filter(action='automation.run_approved').exists())

    def test_consentimento_retirado_antes_da_aprovacao_bloqueia(self):
        contact = self.client_contact(whatsapp_consent=True)
        _, refs = self.case_with_movement(client=contact)
        rule = self.rule('andamento_avisa_cliente')
        run = engine.execute(rule.pk, refs, 'k')
        Contact.objects.filter(pk=contact.pk).update(opted_out=True)
        with mock.patch('integrations.evolution.WhatsAppEvolutionExecutor.send') as send:
            run = engine.approve(run, self.member)
            send.assert_not_called()
        self.assertEqual(run.status, S.FAILED)
        self.assertEqual(run.steps[0]['status'], 'bloqueado')

    def test_sem_cliente_vinculado_nao_fica_pendente(self):
        _, refs = self.case_with_movement()
        run = engine.execute(self.rule('andamento_avisa_cliente').pk, refs, 'k')
        self.assertEqual(run.status, S.FAILED)
        self.assertIn('vincule o cliente', run.steps[0]['detalhe'])

    def test_email_sem_aprovacao_quando_a_regra_dispensa_e_recusa(self):
        contact = self.client_contact(email_consent=True, kind='cliente')
        rule = self.rule('cliente_boas_vindas', require_approval=False)
        run = engine.execute(rule.pk, {'contact_id': contact.pk, 'user_id': str(self.member.pk)}, 'c1')
        self.assertEqual(run.status, S.SUCCESS, run.steps)
        self.assertEqual(mail.outbox[-1].to, ['maria@x.com'])
        self.assertIn('Olá, Maria!', mail.outbox[-1].body)
        self.assertIn('Para não receber mais', mail.outbox[-1].body)
        rule.require_approval = True
        rule.save()
        run = engine.execute(rule.pk, {'contact_id': contact.pk}, 'c2')
        self.assertEqual(run.status, S.PENDING)
        res = self.c.post(f'/api/v1/automations/runs/{run.pk}/reject/', {'motivo': 'texto errado'}, format='json')
        self.assertEqual(res.json()['status'], S.REJECTED)
        self.assertEqual(len(mail.outbox), 1)

    def test_passos_cifrados_no_banco(self):
        contact = self.client_contact(whatsapp_consent=True)
        _, refs = self.case_with_movement(client=contact)
        engine.execute(self.rule('andamento_avisa_cliente').pk, refs, 'k')
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT title, steps FROM automations_rulerun')
            title, steps = cur.fetchone()
        self.assertTrue(title.startswith('enc::') and steps.startswith('enc::'))
        self.assertNotIn('Maria', steps)

    def test_limite_diario_pausa_a_regra(self):
        _, refs = self.case_with_movement()
        rule = self.rule('andamento_cria_tarefa')
        with mock.patch.object(engine, 'DAILY_LIMIT', 1):
            self.assertEqual(engine.execute(rule.pk, refs, 'a').status, S.SUCCESS)
            run = engine.execute(rule.pk, refs, 'b')
            self.assertIsNone(engine.execute(rule.pk, refs, 'c'))
        self.assertEqual(run.status, S.FAILED)
        rule.refresh_from_db()
        self.assertFalse(rule.enabled)

    def test_documento_confirmado_tarefa_na_vespera_do_prazo(self):
        from documents.models import Document, DocumentExtraction
        doc = Document.objects.create(organization=self.org, nome='intimacao.pdf', uploaded_by=self.member)
        ex = DocumentExtraction.objects.create(document=doc, status='confirmed', fields={
            'tipo_documento': 'Intimação', 'prazos': [{'descricao': 'Contestação', 'data': '2026-02-19', 'fatal': True}]})
        rule = self.rule('documento_prazo_fatal')
        with mock.patch('django.utils.timezone.localdate', return_value=datetime(2026, 2, 2).date()):
            run = engine.execute(rule.pk, {'extraction_id': ex.pk, 'user_id': str(self.member.pk)}, 'd')
        self.assertEqual(run.status, S.SUCCESS, run.steps)
        task = UserTask.objects.get()
        self.assertEqual(timezone.localtime(task.scheduled_at).date().isoformat(), '2026-02-18')   # 1 dia útil antes (quarta de cinzas)
        self.assertEqual(task.priority, 'alta')


class TickAndHookTests(Base):
    def test_agenda_semanal_roda_uma_vez(self):
        rule = self.rule('semanal_revisao')
        monday = at(2026, 3, 9, 10)
        with mock.patch('django.utils.timezone.localdate', return_value=monday.date()):
            self.assertEqual(engine.tick(monday)['schedule'], 1)
            self.assertEqual(engine.tick(monday + timedelta(minutes=15))['schedule'], 0)
            self.assertEqual(engine.tick(at(2026, 3, 9, 7))['schedule'], 0)
        self.assertEqual(engine.tick(at(2026, 3, 10, 10))['schedule'], 0)                # terça
        self.assertEqual(RuleRun.objects.filter(rule=rule).count(), 1)

    def test_prazo_chegando(self):
        self.rule('prazo_lembrete')
        UserTask.objects.create(titulo='Prazo: Contestação', responsavel=self.member, scheduled_at=at(2026, 3, 12, 9))
        UserTask.objects.create(titulo='Reunião', responsavel=self.member, scheduled_at=at(2026, 3, 12, 9))
        out = engine.tick(at(2026, 3, 9, 8))                                            # segunda + 3 dias úteis = quinta
        self.assertEqual(out['deadline'], 1)
        self.assertEqual(engine.tick(at(2026, 3, 9, 9))['deadline'], 0)
        from notifications.models import Notification
        self.assertTrue(Notification.objects.filter(title='Prazo em 3 dias úteis', user=self.member).exists())

    def test_aprovacao_expira(self):
        contact = self.client_contact(whatsapp_consent=True)
        _, refs = self.case_with_movement(client=contact)
        run = engine.execute(self.rule('andamento_avisa_cliente').pk, refs, 'k')
        RuleRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=8))
        run.refresh_from_db()
        with self.assertRaises(engine.DecisionError):
            engine.approve(run, self.member)
        self.assertEqual(engine.tick()['expired'], 1)
        run.refresh_from_db()
        self.assertEqual(run.status, S.EXPIRED)

    def test_emit_enfileira_so_ids_e_so_se_houver_regra(self):
        with mock.patch('core.queue.enqueue') as enq:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(engine.emit(self.org, 'contact_created', {'contact_id': 1}, 'x'), 0)
            enq.assert_not_called()
            self.rule('cliente_boas_vindas')
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(engine.emit(self.org, 'contact_created', {'contact_id': 1}, 'x'), 1)
            self.assertEqual(enq.call_args.args[0], 'automations.engine.execute')
            self.assertEqual(enq.call_args.args[2], {'contact_id': 1})
            enq.side_effect = RuntimeError('redis fora')
            with self.captureOnCommitCallbacks(execute=True):
                engine.emit(self.org, 'contact_created', {'contact_id': 1}, 'x')   # não levanta

    def test_ganchos_contato_e_andamento(self):
        self.rule('cliente_boas_vindas')
        with mock.patch('automations.engine.emit') as emit:
            res = self.c.post('/api/v1/contacts/', {'name': 'Pedro Alves', 'email': 'p@x.com'}, format='json')
            self.assertEqual(res.status_code, 201, res.content)
            self.assertEqual(emit.call_args.args[1], 'contact_created')
        res = self.c.post('/api/v1/research/cases/', {'cnj': '0000832-35.2018.4.01.3202', 'cliente_id': res.json()['id']}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['cliente']['nome'], 'Pedro Alves')
        cid = res.json()['id']
        self.assertEqual(self.c.patch(f'/api/v1/research/cases/{cid}/', {'cliente_id': None}, format='json').json()['cliente'], None)
        self.assertEqual(self.c.patch(f'/api/v1/research/cases/{cid}/', {'cliente_id': 99999}, format='json').status_code, 400)
        from research.monitor import check_case
        case = MonitoredCase.objects.get(pk=cid)
        mov = {'digest': 'd1', 'occurred_at': at(2026, 3, 2), 'code': '1', 'name': 'Juntada', 'complement': ''}
        with mock.patch('research.providers.datajud.search_case', return_value={'movements': [mov]}), \
                mock.patch('automations.engine.emit') as emit, mock.patch('research.monitor._notify'):
            check_case(case)
            emit.assert_not_called()                                                     # 1ª consulta só grava histórico
            with mock.patch('research.providers.datajud.search_case', return_value={'movements': [mov, {**mov, 'digest': 'd2'}]}):
                check_case(case)
            self.assertEqual(emit.call_args.args[1:3], ('case_movement', {'case_id': cid, 'digests': ['d2']}))
