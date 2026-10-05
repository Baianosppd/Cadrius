from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from backoffice import obligations
from backoffice.tests import staff
from billing.models import FiscalObligation, Payment
from cadrius.tests_security import make_org, make_user
from notifications.models import Notification

FISCAL = dict(FISCAL_NFSE_PROVIDER='focusnfe', FOCUSNFE_TOKEN='tok', CADRIUS_FISCAL_CNPJ='12345678000199', CADRIUS_FISCAL_IM='123',
              CADRIUS_FISCAL_COD_MUNICIPIO='3550308', CADRIUS_FISCAL_ITEM_SERVICO='1.05', CADRIUS_FISCAL_ALIQUOTA_ISS='2',
              FISCAL_RETENCOES_PJ={'IRRF': 1.5})


def resp(code, body):
    return mock.Mock(status_code=code, json=lambda: body)


class NfseTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org('Escritório Alfa')
        self.org.cnpj, self.org.razao_social = '11222333000181', 'Alfa Advogados'
        self.org.save()
        make_user('dono@alfa.com', self.org, role='OWNER')
        self.pay = Payment.objects.create(organization=self.org, kind='subscription', description='Plano Pro', amount_cents=19900,
                                          paid_at=timezone.now(), stripe_id='in_1')
        self.c = APIClient()
        self.c.force_authenticate(staff('fiscal@cadrius.ia.br', 'fiscal'), token={'amr': 'mfa'})
        self.url = f'/api/v1/backoffice/fiscal/payments/{self.pay.pk}/nfse/'

    def test_conferencia_sem_emissor_aponta_o_que_falta(self):
        res = self.c.get(self.url).json()
        self.assertFalse(res['automatico'])
        self.assertTrue(any('CNPJ da Cadrius' in f for f in res['faltando']))
        self.assertIn('2027', res['reforma']['observacao'])
        self.assertEqual(self.c.post(self.url, {'acao': 'emitir', 'reason': 'conferido'}, format='json').status_code, 400)

    @override_settings(**FISCAL)
    def test_emitir_consultar_e_cancelar(self):
        pv = self.c.get(self.url).json()
        self.assertEqual((pv['faltando'], pv['iss'], pv['retencoes'][0]['valor']), ([], '3.98', '2.99'))
        self.assertEqual(pv['nota']['tomador']['cnpj'], '11222333000181')
        with mock.patch('backoffice.nfse.requests.request') as req:
            req.side_effect = [resp(202, {'status': 'processando_autorizacao'}),
                               resp(200, {'status': 'autorizado', 'numero': '77', 'url': 'https://nfse.exemplo/77', 'data_emissao': '2026-10-05'})]
            self.assertEqual(self.c.post(self.url, {'acao': 'emitir'}, format='json').status_code, 400)       # sem observação
            res = self.c.post(self.url, {'acao': 'emitir', 'reason': 'conferido com o contador'}, format='json').json()
        self.assertEqual((res['nf_status'], res['nf_numero'], res['nfse_url']), ('issued', '77', 'https://nfse.exemplo/77'))
        self.assertEqual(req.call_args_list[0].kwargs['params'], {'ref': f'cadrius-{self.pay.pk}'})
        self.assertEqual(req.call_args_list[0].kwargs['auth'], ('tok', ''))
        self.assertEqual(self.c.post(self.url, {'acao': 'emitir', 'reason': 'de novo'}, format='json').status_code, 400)
        self.assertEqual(self.c.post(self.url, {'acao': 'cancelar', 'justificativa': 'curta'}, format='json').status_code, 400)
        with mock.patch('backoffice.nfse.requests.request', return_value=resp(200, {'status': 'cancelado'})):
            res = self.c.post(self.url, {'acao': 'cancelar', 'justificativa': 'Valor emitido em duplicidade'}, format='json').json()
        self.assertEqual(res['nf_status'], 'canceled')

    @override_settings(**FISCAL)
    def test_erro_do_emissor_e_sincronizacao(self):
        from backoffice import nfse
        with mock.patch('backoffice.nfse.requests.request', return_value=resp(422, {'erros': [{'mensagem': 'Tomador sem endereço'}]})):
            res = self.c.post(self.url, {'acao': 'emitir', 'reason': 'conferido'}, format='json').json()
        self.assertEqual((res['nf_status'], res['nfse_erro']), ('error', 'Tomador sem endereço'))
        Payment.objects.filter(pk=self.pay.pk).update(invoice_status='processing', nfse_ref='r1')
        with mock.patch('backoffice.nfse.requests.request', return_value=resp(200, {'status': 'autorizado', 'numero': '8'})):
            self.assertEqual(nfse.sync_processing()['emitidas'], 1)

    def test_so_area_fiscal(self):
        other = APIClient()
        other.force_authenticate(staff('ti@cadrius.ia.br', 'ti'), token={'amr': 'mfa'})
        self.assertEqual(other.get(self.url).status_code, 403)


class ObligationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = staff('fiscal@cadrius.ia.br', 'fiscal')
        self.c = APIClient()
        self.c.force_authenticate(self.user, token={'amr': 'mfa'})

    def test_vencimentos_com_dia_util(self):
        das = FiscalObligation.objects.get(code='pgdas-das')
        self.assertEqual(obligations.due_for(das, '2026-08'), date(2026, 9, 21))        # 20/09/2026 é domingo → posterga
        dctf = FiscalObligation.objects.get(code='dctfweb')
        self.assertEqual(obligations.due_for(dctf, '2026-09'), date(2026, 10, 30))      # último dia útil de outubro
        reinf = FiscalObligation.objects.get(code='efd-reinf')
        self.assertEqual(obligations.due_for(reinf, '2026-10'), date(2026, 11, 13))     # 15/11 feriado (domingo) → antecipa
        defis = FiscalObligation.objects.get(code='defis')
        self.assertEqual(obligations.due_for(defis, '2027'), date(2027, 3, 31))

    def test_marcar_feito_editar_e_lembrar(self):
        today = date(2026, 10, 15)
        rows = obligations.upcoming(today)
        das = next(r for r in rows if r['codigo'] == 'pgdas-das' and r['competencia'] == '2026-09')
        self.assertEqual((das['vencimento'], das['situacao'], das['dias']), (date(2026, 10, 20), 'pendente', 5))
        self.assertEqual(obligations.remind(today) >= 1, True)
        self.assertEqual(obligations.remind(today), 0)                                   # não repete
        self.assertTrue(Notification.objects.filter(user=self.user, dedupe_key__startswith='fiscal:pgdas-das:2026-09').exists())
        url = f'/api/v1/backoffice/fiscal/obligations/{das["obrigacao_id"]}/done/'
        self.assertEqual(self.c.post(url, {'competencia': '2026'}, format='json').status_code, 400)
        res = self.c.post(url, {'competencia': '2026-09', 'obs': 'pago'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.c.post(url, {'competencia': '2026-09'}, format='json').status_code, 400)
        res = self.c.patch('/api/v1/backoffice/fiscal/obligations/', {'id': das['obrigacao_id'], 'dia': 32, 'reason': 'mudança'}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.c.patch('/api/v1/backoffice/fiscal/obligations/', {'id': das['obrigacao_id'], 'ativa': False, 'reason': 'sem DAS'}, format='json')
        self.assertFalse(res.json()['ativa'])
        self.assertNotIn('pgdas-das', {r['codigo'] for r in self.c.get('/api/v1/backoffice/fiscal/obligations/').json()['proximos']})
        self.assertTrue(timedelta)
