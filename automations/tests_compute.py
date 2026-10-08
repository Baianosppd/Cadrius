"""CAD-230: cálculos, tabelas temporárias, passos condicionais e ações do Google nas regras."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from automations import catalog, compute, engine
from automations.models import Rule, RuleRun
from automations.tests import Base
from carteira.models import Receivable
from gcal.models import GoogleCalendarApp, GoogleCalendarLink
from gcal.platform import DRIVE_FILE
from tasks.models import UserTask

S = RuleRun.Status


class EvaluatorTests(Base):
    def ctx(self):
        return {'honorario': {'valor': 'R$ 1.500,00', 'dias_atraso': '10', 'vencimento': '01/10/2026'}, 'hoje': '11/10/2026'}

    def test_contas_em_portugues(self):
        c = self.ctx()
        self.assertEqual(compute.evaluate('{{honorario.valor}} * 2%', c), Decimal('30'))
        self.assertEqual(compute.evaluate('{{honorario.valor}} * 0,02 + {{honorario.valor}} * 0,00033 * {{honorario.dias_atraso}}', c),
                         Decimal('34.95'))
        self.assertEqual(compute.evaluate('arredondar({{honorario.valor}} / 7; 2)', c), Decimal('214.29'))
        self.assertEqual(compute.evaluate('maximo(10; {{honorario.dias_atraso}}; 3)', c), Decimal('10'))
        self.assertEqual(compute.evaluate('se({{honorario.dias_atraso}} > 5; 100; 0)', c), Decimal('100'))
        self.assertEqual(compute.evaluate('dias_entre({{honorario.vencimento}}; {{hoje}})', c), Decimal('10'))
        self.assertEqual(compute.fmt(Decimal('1234.5'), 'moeda'), 'R$ 1.234,50')
        self.assertEqual(compute.fmt(Decimal('0.125'), 'percentual'), '12,50%')

    def test_nada_alem_de_conta(self):
        c = self.ctx()
        for bad in ('__import__("os").system("id")', '().__class__', 'open("x")', 'valor * 2', '[1, 2]', 'lambda: 1',
                    '9 ** 99999', '1 / 0', '{{honorario.valor}}.real', 'x if 1 else 2'):
            with self.assertRaises(compute.ComputeError, msg=bad):
                compute.evaluate(bad, c)
        with self.assertRaises(compute.ComputeError):
            compute.evaluate('a' * 500, c)

    def test_validacao_ao_salvar(self):
        ok = {'type': 'calcular', 'params': {'nome': 'multa', 'expressao': '{{honorario.valor}} * 2%', 'formato': 'moeda'}}
        catalog.clean_actions('receivable_due', [ok, {'type': 'notify', 'params': {'titulo': 'Multa', 'mensagem': '{{calc.multa}}'}}])
        with self.assertRaises(catalog.RuleError):
            catalog.clean_actions('receivable_due', [{'type': 'calcular', 'params': {'nome': 'Multa!', 'expressao': '1'}}])
        with self.assertRaises(catalog.RuleError):
            catalog.clean_actions('receivable_due', [{'type': 'calcular', 'params': {'nome': 'x', 'expressao': 'os.system(1)'}}])
        with self.assertRaises(catalog.RuleError):                       # tabela usada antes de ser montada
            catalog.clean_actions('schedule', [{'type': 'google_planilha', 'params': {'planilha': 'P', 'tabela': 'abertos'}}])
        with self.assertRaises(catalog.RuleError):                       # comparação numérica sem número
            catalog.clean_actions('receivable_due', [ok, {'type': 'notify', 'params': {'titulo': 'a', 'mensagem': 'b'},
                                                          'somente_se': {'field': 'calc.multa_valor', 'op': 'gt', 'value': ''}}])
        with self.assertRaises(catalog.RuleError):                       # condição sobre cálculo que não existe
            catalog.clean_actions('schedule', [{'type': 'notify', 'params': {'titulo': 'a', 'mensagem': 'b'},
                                                'somente_se': {'field': 'calc.x_valor', 'op': 'gt', 'value': '1'}}])


class RuleProcessingTests(Base):
    def setUp(self):
        super().setUp()
        self.maria = self.client_contact()
        today = timezone.localdate()
        self.rec = Receivable.objects.create(organization=self.org, contact=self.maria, description='Parcela 1', amount_cents=150000,
                                             due_date=today - timedelta(days=10))
        Receivable.objects.create(organization=self.org, contact=self.maria, description='Parcela 2', amount_cents=50000,
                                  due_date=today + timedelta(days=20))

    def make(self, actions, trigger='receivable_due', config=None):
        body = catalog.clean_rule({'name': 'Cobrança com multa', 'trigger': trigger, 'trigger_config': config or {'quando': 'vencido'},
                                   'actions': actions})
        return Rule.objects.create(organization=self.org, enabled=True, created_by=self.owner, require_approval=True, **body)

    def test_calculo_tabela_e_passo_condicional(self):
        rule = self.make([
            {'type': 'calcular', 'params': {'nome': 'multa', 'expressao': '{{honorario.valor}} * 2% + {{honorario.valor}} * 0,033% * '
                                                                          '{{honorario.dias_atraso}}', 'formato': 'moeda'}},
            {'type': 'tabela', 'params': {'nome': 'abertos', 'fonte': 'honorarios_em_aberto', 'do_cliente': 'sim'}},
            {'type': 'notify', 'params': {'titulo': 'Multa de {{cliente.primeiro_nome}}',
                                          'mensagem': 'Multa {{calc.multa}}. Em aberto: {{tabela.abertos.quantidade}} '
                                                      '({{tabela.abertos.total}})\n{{tabela.abertos.texto}}'}},
            {'type': 'create_task', 'params': {'titulo': 'Ligar para {{cliente.nome}}', 'quando': 'dias_uteis', 'dias': 0},
             'somente_se': {'field': 'calc.multa_valor', 'op': 'gt', 'value': '1000'}},
        ])
        run = engine.execute(rule.pk, {'receivable_id': self.rec.pk}, 'k1')
        self.assertEqual(run.status, S.SUCCESS, run.steps)
        calc, table, notify, task = run.steps
        self.assertEqual(calc['detalhe'], 'multa = R$ 34,95')
        self.assertIn('2 linha(s), total R$ 2.000,00', table['detalhe'])
        self.assertEqual(task['status'], 'pulado')                  # multa < 1000: não cria tarefa
        self.assertEqual(UserTask.objects.count(), 0)
        from notifications.models import Notification
        n = Notification.objects.filter(organization=self.org).latest('pk')
        self.assertIn('Multa R$ 34,95. Em aberto: 2 (R$ 2.000,00)', n.description)
        self.assertIn('Parcela 1', n.description)

    def test_simulacao_mostra_os_numeros(self):
        rule = self.make([{'type': 'calcular', 'params': {'nome': 'total', 'expressao': '{{honorario.valor}} * 1,1',
                                                          'formato': 'moeda'}},
                          {'type': 'notify', 'params': {'titulo': 'Total', 'mensagem': '{{calc.total}}'}}])
        sim = engine.simulate(rule)
        self.assertEqual(sim['passos'][0]['detalhe'][:8], 'total = ')
        self.assertIn('calc.total', sim['variaveis'])

    def test_comparacao_numerica_nas_condicoes(self):
        ctx = {'honorario': {'valor': 'R$ 1.500,00'}}
        self.assertTrue(engine.condition_ok({'field': 'honorario.valor', 'op': 'gte', 'value': '1500'}, ctx))
        self.assertFalse(engine.condition_ok({'field': 'honorario.valor', 'op': 'lt', 'value': '1.000,00'}, ctx))
        self.assertFalse(engine.condition_ok({'field': 'honorario.nada', 'op': 'gt', 'value': '0'}, ctx))

    def test_planilha_e_agenda_do_google(self):
        app = GoogleCalendarApp.objects.create(organization=self.org, client_id='x.apps.googleusercontent.com', client_secret='s')
        GoogleCalendarLink.objects.create(user=self.owner, app=app, refresh_token='r', scopes=f'openid {DRIVE_FILE}')
        rule = self.make([
            {'type': 'tabela', 'params': {'nome': 'abertos', 'fonte': 'honorarios_em_aberto'}},
            {'type': 'google_planilha', 'params': {'planilha': 'Cobranças', 'tabela': 'abertos'}},
            {'type': 'google_evento', 'params': {'titulo': 'Cobrar {{cliente.nome}}', 'quando': 'dias_uteis', 'dias': 1,
                                                 'hora': '14:30', 'duracao_min': 30}},
        ])
        with mock.patch('gcal.workspace.append_rows', return_value=mock.Mock(url='https://docs.google.com/x')) as rows, \
                mock.patch('gcal.write.create_event', return_value=mock.Mock(pk=7)) as event:
            run = engine.execute(rule.pk, {'receivable_id': self.rec.pk}, 'k2')
        self.assertEqual(run.status, S.SUCCESS, run.steps)
        args = rows.call_args
        self.assertEqual(args.args[1], 'Cobranças')
        self.assertEqual(len(args.args[2]), 2)                          # as 2 parcelas em aberto
        self.assertEqual(args.args[3][0], 'Cliente')
        self.assertEqual(event.call_args.kwargs['titulo'], 'Cobrar Maria Clara Souza')
        self.assertEqual(timezone.localtime(event.call_args.kwargs['inicio']).strftime('%H:%M'), '14:30')

    def test_sem_google_conectado_fica_bloqueado_sem_derrubar_o_resto(self):
        rule = self.make([{'type': 'notify', 'params': {'titulo': 'a', 'mensagem': 'b'}},
                          {'type': 'google_planilha', 'params': {'planilha': 'P', 'colunas': 'Cliente={{cliente.nome}}'}}])
        run = engine.execute(rule.pk, {'receivable_id': self.rec.pk}, 'k3')
        self.assertEqual(run.status, S.PARTIAL)
        self.assertIn('Google conectado', run.steps[1]['detalhe'])
