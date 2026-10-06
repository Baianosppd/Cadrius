"""CAD-223: despesas fixas, fluxo de caixa, indicadores, fiscal do escritório, pacote do contador e NFS-e pelo Asaas."""
from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from carteira import reports
from carteira.models import Expense, FinanceSettings, Receivable, RecurringExpense
from contacts.models import Contact

BASE = '/api/v1/carteira/financeiro/'


class FinanceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.pf = Contact.objects.create(organization=self.org, name='Maria PF', person_type='PF', document='529.982.247-25')
        self.pj = Contact.objects.create(organization=self.org, name='Empresa PJ', person_type='PJ')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        on_commit = mock.patch('django.db.transaction.on_commit', side_effect=lambda fn: fn())
        on_commit.start()
        self.addCleanup(on_commit.stop)

    def rec(self, contact, cents, *, paid=None, due=None, **kw):
        today = timezone.localdate()
        return Receivable.objects.create(organization=self.org, contact=contact, description='Parcela', amount_cents=cents,
                                         due_date=due or today, status='pago' if paid else 'aberto', paid_at=paid,
                                         paid_cents=cents if paid else 0, **kw)

    def test_despesa_fixa_lanca_uma_vez_por_mes(self):
        res = self.c.post(f'{BASE}recorrentes/', {'descricao': 'Aluguel', 'valor': '2.500,00', 'dia': 5, 'inicio': '2030-01-01'},
                          format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(self.c.post(f'{BASE}recorrentes/', {'descricao': 'X', 'valor': '10', 'dia': 31}, format='json').status_code, 400)
        self.assertEqual(reports.generate_recurring(date(2030, 1, 4)), 0)          # antes do dia
        self.assertEqual(reports.generate_recurring(date(2030, 1, 5)), 1)
        self.assertEqual(reports.generate_recurring(date(2030, 1, 20)), 0)         # já lançada no mês
        self.assertEqual(reports.generate_recurring(date(2030, 2, 6)), 1)
        self.assertEqual(Expense.objects.filter(description__startswith='Aluguel').count(), 2)
        self.assertEqual(self.c.get(f'{BASE}recorrentes/').data['total_mensal_centavos'], 250000)

    def test_fluxo_de_caixa_e_indicadores(self):
        today = timezone.localdate()
        self.rec(self.pf, 100000, due=today + timedelta(days=2))
        self.rec(self.pf, 50000, due=today - timedelta(days=40))
        RecurringExpense.objects.create(organization=self.org, description='Sistema', amount_cents=30000, day=28, starts_on=today)
        flow = self.c.get(f'{BASE}fluxo/?semanas=8').data
        self.assertEqual(len(flow['semanas']), 8)
        self.assertEqual(flow['entradas_centavos'], 100000)
        self.assertEqual(flow['vencido_centavos'], 50000)
        self.assertGreaterEqual(flow['saidas_centavos'], 30000)
        self.c.patch(f'{BASE}config/', {'meta_mensal': '10.000,00'}, format='json')
        self.rec(self.pj, 400000, paid=today)
        ind = self.c.get(f'{BASE}indicadores/').data
        self.assertEqual(ind['meta']['pct'], 40)
        aging = {a['faixa']: a['centavos'] for a in ind['inadimplencia']}
        self.assertEqual(aging['31_60'], 50000)
        self.assertEqual(ind['dre']['receitas'], 400000)

    def test_fiscal_simples_presumido_e_autonomo(self):
        today = timezone.localdate()
        self.rec(self.pf, 1000000, paid=today)
        self.rec(self.pj, 500000, paid=today)
        cfg = FinanceSettings.of(self.org)
        cfg.regime = 'simples'
        cfg.save()
        f = self.c.get(f'{BASE}fiscal/').data
        self.assertEqual((f['pessoa_fisica_centavos'], f['pessoa_juridica_centavos']), (1000000, 500000))
        self.assertEqual(f['estimativa']['itens'][0]['centavos'], 67500)          # 4,5% (1ª faixa do Anexo IV)
        self.assertEqual(f['sem_nota'], 2)
        self.assertEqual(reports.simples_rate(500_000_00), reports.simples_rate(500_000_00).quantize(reports.Decimal('0.0001')))
        self.assertAlmostEqual(float(reports.simples_rate(500_000_00)), (500_000 * 0.102 - 12_420) / 500_000, places=4)
        self.c.patch(f'{BASE}config/', {'regime': 'presumido', 'iss_pct': '5'}, format='json')
        nomes = [i['nome'] for i in self.c.get(f'{BASE}fiscal/').data['estimativa']['itens']]
        self.assertIn('IRPJ', nomes)
        self.c.patch(f'{BASE}config/', {'regime': 'autonomo'}, format='json')
        est = self.c.get(f'{BASE}fiscal/').data['estimativa']
        self.assertEqual(est['itens'][0]['centavos'], 1000000)                    # Carnê-Leão: só pessoa física
        self.assertEqual(self.c.patch(f'{BASE}config/', {'iss_pct': '9'}, format='json').status_code, 400)

    def test_pacote_do_contador_auditado_e_sem_acesso_para_membro(self):
        self.rec(self.pf, 120000, paid=timezone.localdate())
        res = self.c.get(f'{BASE}contador.csv')
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn('529.982.247-25', body)
        self.assertIn('1200,00', body)
        self.assertTrue(AuditEvent.objects.filter(action='data.export').exists())
        m = APIClient()
        m.force_authenticate(self.member)
        self.assertEqual(m.get(f'{BASE}contador.csv').status_code, 403)

    def test_nfse_pelo_asaas_e_webhook_dispara_gatilho(self):
        from carteira import services
        rec = self.rec(self.pf, 200000, paid=timezone.localdate(), asaas_id='pay_1')
        with mock.patch('integrations.services.org_connection', return_value=mock.Mock(credentials={'api_key': 'k'})), \
                mock.patch('integrations.services._asaas', return_value={'id': 'inv_1', 'status': 'SCHEDULED', 'pdfUrl': ''}) as api:
            res = self.c.post(f'/api/v1/carteira/lancamentos/{rec.pk}/nota/', {}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(api.call_args.args[2], '/invoices')
        rec.refresh_from_db()
        self.assertEqual((rec.nfse_id, rec.nfse_status), ('inv_1', 'SCHEDULED'))
        with mock.patch('automations.engine.emit') as emit:
            out = services.handle_asaas_event(self.org, {'id': 'evt_9', 'event': 'INVOICE_AUTHORIZED',
                                                          'invoice': {'id': 'inv_1', 'status': 'AUTHORIZED', 'pdfUrl': 'https://x/nf.pdf'}})
        self.assertEqual(out, 'nota')
        emit.assert_called_once()
        rec.refresh_from_db()
        self.assertEqual(rec.nfse_url, 'https://x/nf.pdf')
        open_rec = self.rec(self.pf, 1000)
        self.assertEqual(self.c.post(f'/api/v1/carteira/lancamentos/{open_rec.pk}/nota/', {}, format='json').status_code, 400)
