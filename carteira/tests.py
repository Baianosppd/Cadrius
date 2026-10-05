from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from automations import engine
from automations.models import Rule
from carteira import services as svc
from carteira.models import Expense, FeeAgreement, Opportunity, Receivable
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from integrations.models import AppConnection
from research.models import MonitoredCase

BASE = '/api/v1/carteira/'


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.client_c = Contact.objects.create(organization=self.org, name='Maria Cliente', document='52998224725', email='m@c.com',
                                               email_consent=True)
        self.c = APIClient()
        self.c.force_authenticate(self.owner)


class MoneyTests(APITestCase):
    def test_valores_e_parcelas(self):
        self.assertEqual(svc.to_cents('R$ 1.234,56'), 123456)
        self.assertEqual(svc.to_cents('1234.5'), 123450)
        self.assertEqual(svc.to_cents(10), 1000)
        with self.assertRaises(svc.FinanceError):
            svc.to_cents('0')
        self.assertEqual(svc.split(1000, 3), [334, 333, 333])
        self.assertEqual(svc.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(svc.brl(123456), 'R$ 1.234,56')
        rows = svc.schedule_for('mensal', 50000, 3, date(2026, 11, 10))
        self.assertEqual([r[2] for r in rows], [date(2026, 11, 10), date(2026, 12, 10), date(2027, 1, 10)])
        self.assertEqual(svc.schedule_for('exito', 0, 1, None), [])


class FunnelAndAgreementTests(Base):
    def test_funil_ganho_gera_contrato_parcelado_e_baixa(self):
        c = APIClient()
        c.force_authenticate(self.member)
        res = c.post(f'{BASE}oportunidades/', {'contato_id': self.client_c.pk, 'titulo': 'Revisional de aposentadoria', 'origem': 'indicacao',
                                               'valor': '6.000,00', 'proxima_acao': 'Ligar', 'proxima_acao_em': '2026-01-01'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        opp = res.json()
        self.assertTrue(opp['atrasada'])
        self.assertEqual(c.patch(f'{BASE}oportunidades/{opp["id"]}/', {'etapa': 'perdido'}, format='json').status_code, 400)  # sem motivo
        self.assertEqual(c.patch(f'{BASE}oportunidades/{opp["id"]}/', {'etapa': 'proposta'}, format='json').json()['etapa'], 'proposta')
        res = c.post(f'{BASE}contratos/', {'contato_id': self.client_c.pk, 'oportunidade_id': opp['id'], 'tipo': 'parcelado',
                                           'valor': '1000', 'parcelas': 3, 'primeiro_vencimento': '2026-11-10'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        ag = res.json()
        self.assertEqual([x['valor_centavos'] for x in ag['lancamentos']], [33334, 33333, 33333])
        self.assertEqual(Opportunity.objects.get(pk=opp['id']).stage, 'ganho')
        rec = ag['lancamentos'][0]['id']
        self.assertEqual(c.post(f'{BASE}lancamentos/{rec}/baixa/', {}, format='json').status_code, 403)      # membro não dá baixa
        res = self.c.post(f'{BASE}lancamentos/{rec}/baixa/', {'forma': 'pix', 'pago_em': '2026-11-09'}, format='json')
        self.assertEqual((res.json()['status'], res.json()['forma']), ('pago', 'pix'))
        for r in Receivable.objects.filter(agreement_id=ag['id'], status='aberto'):
            svc.mark_paid(r, self.owner, paid_at=date(2026, 11, 20))
        self.assertEqual(FeeAgreement.objects.get(pk=ag['id']).status, 'encerrado')
        summary = self.c.get(f'{BASE}painel/?inicio=2026-11-01&fim=2026-12-31').json()
        self.assertEqual(summary['recebido_centavos'], 100000)
        self.assertEqual(summary['funil']['ganhos'], 1)
        self.assertTrue(AuditEvent.objects.filter(action='crm.agreement_created').exists())

    def test_exito_mensal_e_cancelamento(self):
        ag = svc.create_agreement(self.org, self.owner, contact=self.client_c, title='Trabalhista', kind='exito', success_pct='30')
        self.assertEqual(ag.receivables.count(), 0)
        res = self.c.post(f'{BASE}contratos/{ag.pk}/exito/', {'proveito': '10.000,00', 'vencimento': '2026-12-01'}, format='json')
        self.assertEqual(res.json()['lancamentos'][0]['valor_centavos'], 300000)
        with self.assertRaises(svc.FinanceError):
            svc.create_agreement(self.org, self.owner, contact=self.client_c, title='X', kind='exito', success_pct='0')
        m = svc.create_agreement(self.org, self.owner, contact=self.client_c, title='Partido', kind='mensal', total_cents=50000,
                                 installments=12, first_due=date(2026, 11, 5))
        self.assertEqual(m.receivables.count(), 12)
        self.assertEqual(self.c.post(f'{BASE}contratos/{m.pk}/cancelar/').json()['status'], 'cancelado')
        self.assertFalse(m.receivables.filter(status='aberto').exists())

    def test_despesa_reembolsavel_e_margem(self):
        case = MonitoredCase.objects.create(organization=self.org, cnj='0000832-35.2018.4.01.3202', tribunal='trf1', client=self.client_c)
        c = APIClient()
        c.force_authenticate(self.member)
        today = timezone.localdate().isoformat()
        res = c.post(f'{BASE}despesas/', {'descricao': 'Custas iniciais', 'categoria': 'custas', 'valor': '250,00', 'processo_id': case.pk,
                                          'reembolsavel': True, 'data': today}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['reembolso']['contato']['id'], self.client_c.pk)
        c.post(f'{BASE}despesas/', {'descricao': 'Correspondente', 'categoria': 'diligencia', 'valor': 100, 'contato_id': self.client_c.pk,
                                    'data': today}, format='json')
        self.assertEqual(c.delete(f'{BASE}despesas/{res.json()["id"]}/').status_code, 403)
        s = self.c.get(f'{BASE}painel/').json()
        self.assertEqual((s['despesas_centavos'], s['reembolsaveis_centavos'], s['a_receber_centavos']), (10000, 25000, 25000))
        self.assertEqual(self.c.delete(f'{BASE}despesas/{res.json()["id"]}/').status_code, 204)
        self.assertFalse(Receivable.objects.exists())

    def test_isolamento_e_ficha_do_cliente(self):
        svc.create_agreement(self.org, self.owner, contact=self.client_c, title='A', kind='avista', total_cents=1000, first_due=date(2026, 1, 1))
        other = APIClient()
        other_org = make_org('Outro')
        other.force_authenticate(make_user('o@y.com', other_org, role='OWNER'))
        self.assertEqual(other.get(f'{BASE}contratos/').json()['resultados'], [])
        self.assertEqual(other.get(f'{BASE}clientes/{self.client_c.pk}/').status_code, 404)
        self.assertEqual(other.post(f'{BASE}oportunidades/', {'contato_id': self.client_c.pk, 'titulo': 'x'}, format='json').status_code, 400)
        ficha = self.c.get(f'{BASE}clientes/{self.client_c.pk}/').json()
        self.assertEqual(ficha['financeiro']['vencido_centavos'], 1000)
        m = APIClient()
        m.force_authenticate(self.member)
        self.assertNotIn('financeiro', m.get(f'{BASE}clientes/{self.client_c.pk}/').json())   # membro não vê valores
        self.assertEqual(m.get(f'{BASE}painel/').status_code, 403)


class AsaasTests(Base):
    def setUp(self):
        super().setUp()
        self.conn = AppConnection.objects.create(user=self.owner, name='Asaas', app_name='ASAAS', credentials={'api_key': 'k', 'ambiente': 'sandbox'})
        self.rec = Receivable.objects.create(organization=self.org, contact=self.client_c, description='Honorários', amount_cents=150000,
                                             due_date=timezone.localdate() + timedelta(days=5))

    def test_cobrar_e_baixa_pelo_webhook_idempotente(self):
        with mock.patch('integrations.services.asaas_charge', return_value={'id': 'pay_1', 'link': 'https://asaas.com/i/1'}) as call:
            res = self.c.post(f'{BASE}lancamentos/{self.rec.pk}/cobrar/', {'forma': 'PIX'}, format='json')
        self.assertEqual(res.json()['link_pagamento'], 'https://asaas.com/i/1', res.content)
        self.assertEqual(call.call_args.kwargs['billing_type'], 'PIX')
        self.assertEqual(self.c.post(f'{BASE}lancamentos/{self.rec.pk}/cobrar/').status_code, 400)          # já cobrado
        cfg = self.c.post(f'{BASE}asaas/webhook-config/').json()
        self.assertIn(f'/asaas/webhook/{self.conn.pk}/', cfg['url'])
        hook = APIClient()
        url = f'{BASE}asaas/webhook/{self.conn.pk}/'
        body = {'id': 'evt_1', 'event': 'PAYMENT_RECEIVED', 'payment': {'id': 'pay_1', 'value': 1500.0, 'billingType': 'PIX',
                                                                         'paymentDate': '2026-10-05'}}
        self.assertEqual(hook.post(url, body, format='json').status_code, 401)
        self.assertEqual(hook.post(url, body, format='json', HTTP_ASAAS_ACCESS_TOKEN='errado' * 8).status_code, 401)
        res = hook.post(url, body, format='json', HTTP_ASAAS_ACCESS_TOKEN=cfg['token'])
        self.assertEqual(res.json()['resultado'], 'pago')
        self.assertEqual(hook.post(url, body, format='json', HTTP_ASAAS_ACCESS_TOKEN=cfg['token']).json()['resultado'], 'duplicado')
        self.rec.refresh_from_db()
        self.assertEqual((self.rec.status, self.rec.method, self.rec.paid_at), ('pago', 'pix', date(2026, 10, 5)))
        refund = {'id': 'evt_2', 'event': 'PAYMENT_REFUNDED', 'payment': {'id': 'pay_1'}}
        self.assertEqual(hook.post(url, refund, format='json', HTTP_ASAAS_ACCESS_TOKEN=cfg['token']).json()['resultado'], 'reaberto')

    def test_cobranca_de_contatos_vira_lancamento(self):
        with mock.patch('integrations.services.asaas_charge', return_value={'id': 'pay_9', 'link': 'https://asaas.com/i/9'}):
            res = self.c.post('/api/v1/integrations/charge/', {'contato_id': self.client_c.pk, 'valor': '300,00',
                                                               'vencimento': (timezone.localdate() + timedelta(days=3)).isoformat()}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        rec = Receivable.objects.get(pk=res.json()['lancamento_id'])
        self.assertEqual((rec.amount_cents, rec.asaas_id), (30000, 'pay_9'))


class ReguaTests(Base):
    def test_regua_de_cobranca_dispara_regra(self):
        today = timezone.localdate()
        rec = Receivable.objects.create(organization=self.org, contact=self.client_c, description='Parcela 1/2', amount_cents=50000,
                                        due_date=today - timedelta(days=5))
        res = self.c.post('/api/v1/automations/rules/', {'modelo': 'regua_vencido'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        rule = Rule.objects.get(pk=res.json()['id'])
        self.assertEqual(rule.trigger_config, {'quando': 'vencido', 'dias': 5})
        sim = self.c.post(f'/api/v1/automations/rules/{rule.pk}/simulate/').json()
        self.assertEqual(sim['origem'], 'real')
        self.assertIn('R$ 500,00', sim['passos'][0]['detalhe'] + str(sim['passos'][0].get('dados')))
        self.c.post(f'/api/v1/automations/rules/{rule.pk}/enable/', {'ativa': True}, format='json')
        noon = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time())) + timedelta(hours=12)
        out = engine.tick(now=noon)
        self.assertEqual(out['receivable'], 1)
        self.assertEqual(engine.tick(now=noon)['receivable'], 0)                     # não repete no mesmo dia
        self.assertTrue(rec.pk)
        self.assertEqual(Expense.objects.count(), 0)
