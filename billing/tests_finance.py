"""CAD-160: área administrativa do financeiro — preços, pacotes, promoções, informes, pesos e resumo."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Organization
from audit.models import AuditEvent
from billing.credit_weights import credits_for
from billing.models import CreditLot, CreditWeight, PlanPriceHistory, Promotion, PromotionRedemption, SubscriptionPlan
from billing.promotions import PromotionError, discounted_price, validate_promotion
from billing.stripe_sync import apply_event
from cadrius.tests_security import make_org, make_user

BASE = '/api/billing/admin/'


def plan(tier='PRO', price='299', credits=1500, users=5):
    return SubscriptionPlan.objects.create(name=tier.title(), tier=tier, price_brl=Decimal(price), max_users=users, max_ai_extractions=credits)


class StaffOnlyTests(APITestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.staff = make_user('s@cadrius.ia.br')
        self.staff.is_staff = True
        self.staff.save()
        self.staff.groups.add(Group.objects.get_or_create(name='Cadrius Financeiro')[0])   # área Financeiro (CAD-168)

    def test_so_a_equipe_acessa(self):
        for url in ('plans/', 'packs/', 'promotions/', 'notices/', 'credit-weights/', 'summary/', 'price-history/'):
            self.assertEqual(self.client.get(BASE + url).status_code, 401, url)
        self.client.force_authenticate(self.owner)
        for url in ('plans/', 'promotions/', 'summary/'):
            self.assertEqual(self.client.get(BASE + url).status_code, 403, url)
        self.client.force_authenticate(self.staff, token={'amr': 'mfa'})   # sessão com MFA (CAD-169)
        for url in ('plans/', 'packs/', 'promotions/', 'notices/', 'credit-weights/', 'summary/', 'price-history/'):
            self.assertEqual(self.client.get(BASE + url).status_code, 200, url)


class PlanAdminTests(APITestCase):
    def setUp(self):
        self.staff = make_user('s@cadrius.ia.br')
        self.staff.is_staff = True
        self.staff.save()
        self.staff.groups.add(Group.objects.get_or_create(name='Cadrius Financeiro')[0])   # área Financeiro (CAD-168)
        self.client.force_authenticate(self.staff, token={'amr': 'mfa'})   # sessão com MFA (CAD-169)
        self.pro = plan()

    def test_alterar_preco_gera_historico_e_auditoria_e_nao_mexe_na_assinatura_existente(self):
        org = Organization.objects.create(name='Cliente', plan=self.pro, stripe_subscription_id='sub_1')
        resp = self.client.patch(f'{BASE}plans/{self.pro.pk}/', {'price_brl': '349.00', 'max_ai_extractions': 2000}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        hist = PlanPriceHistory.objects.get()
        self.assertEqual((hist.old_price, hist.new_price, hist.old_credits, hist.new_credits), (Decimal('299'), Decimal('349'), 1500, 2000))
        self.assertEqual(hist.changed_by, str(self.staff.pk))
        self.assertTrue(AuditEvent.objects.filter(action='billing.price_changed').exists())
        self.assertTrue(AuditEvent.objects.filter(action='billing.admin_changed').exists())
        org.refresh_from_db()
        self.assertEqual((org.stripe_subscription_id, org.plan_id), ('sub_1', self.pro.pk))   # reajuste não é retroativo
        self.assertEqual(self.client.get(BASE + 'price-history/').data[0]['new_price'], '349.00')

    def test_editar_sem_mudar_preco_nao_polui_o_historico_e_plano_nao_se_apaga(self):
        self.client.patch(f'{BASE}plans/{self.pro.pk}/', {'name': 'Profissional'}, format='json')
        self.assertFalse(PlanPriceHistory.objects.exists())
        self.assertEqual(self.client.delete(f'{BASE}plans/{self.pro.pk}/').status_code, 405)
        self.assertEqual(self.client.patch(f'{BASE}plans/{self.pro.pk}/', {'price_brl': '-1'}, format='json').status_code, 400)

    def test_cria_plano_e_pacote(self):
        self.assertEqual(self.client.post(BASE + 'plans/', {'name': 'Start', 'tier': 'START', 'price_brl': '99', 'max_users': 1,
                                                          'max_ai_extractions': 300}, format='json').status_code, 201)
        self.assertEqual(self.client.post(BASE + 'packs/', {'name': '200', 'credits': 200, 'price_brl': '59'}, format='json').status_code, 201)
        self.assertEqual(self.client.post(BASE + 'packs/', {'name': 'x', 'credits': 0, 'price_brl': '59'}, format='json').status_code, 400)


class PromotionRulesTests(APITestCase):
    def setUp(self):
        self.staff = make_user('s@cadrius.ia.br')
        self.staff.is_staff = True
        self.staff.save()
        self.staff.groups.add(Group.objects.get_or_create(name='Cadrius Financeiro')[0])   # área Financeiro (CAD-168)
        self.client.force_authenticate(self.staff, token={'amr': 'mfa'})   # sessão com MFA (CAD-169)
        self.pro, self.start = plan(), plan('START', '99', 300, 1)
        self.org = Organization.objects.create(name='Cliente', plan=self.pro)

    def create(self, **over):
        data = {'code': 'lancamento20', 'name': 'Lançamento', 'kind': 'percent', 'value': '20', 'duration': 'once', **over}
        return self.client.post(BASE + 'promotions/', data, format='json')

    def test_validacoes_de_cadastro(self):
        resp = self.create()
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['code'], 'LANCAMENTO20')   # sempre maiúsculo
        self.assertEqual(self.create(code='X1', value='100').status_code, 400)
        self.assertEqual(self.create(code='X2', duration='repeating').status_code, 400)
        self.assertEqual(self.create(code='X3', plan_tiers=['NAO_EXISTE']).status_code, 400)
        self.assertEqual(self.create(code='X4', starts_at='2026-12-01T00:00:00Z', ends_at='2026-11-01T00:00:00Z').status_code, 400)
        self.assertEqual(self.create(code='X 5!').status_code, 400)
        self.assertEqual(self.create(code='LANCAMENTO20').status_code, 400)   # duplicado

    def test_desconto_nao_muda_depois_de_usado(self):
        promo = Promotion.objects.create(code='A', name='A', kind='percent', value=10)
        PromotionRedemption.objects.create(promotion=promo, organization=self.org)
        Promotion.objects.filter(pk=promo.pk).update(redemptions_count=1)
        self.assertEqual(self.client.patch(f'{BASE}promotions/{promo.pk}/', {'value': '50'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'{BASE}promotions/{promo.pk}/', {'is_active': False}, format='json').status_code, 200)

    def test_validacao_do_cupom(self):
        now = timezone.now()
        Promotion.objects.create(code='OK', name='ok', kind='percent', value=20)
        promo, final = validate_promotion('ok', self.pro, self.org)       # case-insensitive
        self.assertEqual(final, Decimal('239.20'))
        self.assertEqual(discounted_price(Promotion(kind='amount', value=Decimal('50')), Decimal('299')), Decimal('249.00'))
        cases = {
            'INEXISTENTE': None,
            'OFF': dict(is_active=False),
            'FUTURO': dict(starts_at=now + timedelta(days=1)),
            'VENCIDO': dict(ends_at=now - timedelta(days=1)),
            'SOSTART': dict(plan_tiers=['START']),
            'ESGOTADO': dict(max_redemptions=1, redemptions_count=1),
            'BAIXO': dict(kind='amount', value=Decimal('298.80')),    # deixaria R$ 0,20
        }
        for code, extra in cases.items():
            if extra is not None:
                Promotion.objects.create(code=code, name=code, kind=extra.pop('kind', 'percent'), value=extra.pop('value', 10), **extra)
            with self.assertRaises(PromotionError, msg=code):
                validate_promotion(code, self.pro, self.org)
        PromotionRedemption.objects.create(promotion=promo, organization=self.org)
        with self.assertRaises(PromotionError):                           # um uso por escritório
            validate_promotion('OK', self.pro, self.org)


@mock.patch('billing.promotions.ensure_stripe_coupon', return_value='coupon_1')
@override_settings(STRIPE_SECRET_KEY='sk_test_x')
class PromotionCheckoutTests(APITestCase):
    def setUp(self):
        self.pro = plan()
        self.org = make_org()
        self.org.plan = self.pro
        self.org.save()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.promo = Promotion.objects.create(code='PROMO20', name='20%', kind='percent', value=20, plan_tiers=['PRO'])
        self.client.force_authenticate(self.owner)

    def test_checkout_aplica_cupom_e_grava_metadado(self, _coupon):
        with mock.patch('billing.views.ensure_stripe_coupon', return_value='coupon_1'), \
                mock.patch('billing.views.stripe.checkout.Session.create') as create:
            create.return_value = mock.Mock(url='https://stripe.test/c')
            resp = self.client.post('/api/billing/checkout/', {'plan_id': self.pro.pk, 'promo_code': 'promo20'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['discounts'], [{'coupon': 'coupon_1'}])
        self.assertEqual(kwargs['metadata']['promo_id'], str(self.promo.pk))

    def test_checkout_recusa_cupom_invalido(self, _coupon):
        resp = self.client.post('/api/billing/checkout/', {'plan_id': self.pro.pk, 'promo_code': 'NAOEXISTE'}, format='json')
        self.assertEqual((resp.status_code, resp.data['code']), (400, 'invalid_promotion'))

    def test_validacao_previa(self, _coupon):
        ok = self.client.post('/api/billing/promotions/validate/', {'plan_id': self.pro.pk, 'code': 'PROMO20'}, format='json')
        self.assertEqual((ok.data['valid'], ok.data['discounted']), (True, '239.20'))
        bad = self.client.post('/api/billing/promotions/validate/', {'plan_id': self.pro.pk, 'code': 'X'}, format='json')
        self.assertFalse(bad.data['valid'])

    def session(self, amount, promo=True):
        meta = {'kind': 'subscription', 'plan_id': str(self.pro.pk), **({'promo_id': str(self.promo.pk)} if promo else {})}
        return {'type': 'checkout.session.completed', 'data': {'object': {
            'id': 'cs_1', 'client_reference_id': str(self.org.pk), 'payment_status': 'paid', 'amount_total': amount,
            'subscription': 'sub_1', 'metadata': meta}}}

    def test_webhook_confere_o_valor_com_desconto_e_registra_o_uso_uma_vez(self, _coupon):
        self.assertEqual(apply_event(self.session(29900)), 'ignored:plan_mismatch')   # pagou cheio mas dizia ter cupom: não confere
        self.assertEqual(apply_event(self.session(23920)), 'subscription_active')
        apply_event(self.session(23920))
        self.promo.refresh_from_db()
        self.assertEqual(self.promo.redemptions_count, 1)
        self.assertEqual(PromotionRedemption.objects.count(), 1)

    def test_sem_cupom_o_valor_esperado_continua_o_preco_cheio(self, _coupon):
        self.assertEqual(apply_event(self.session(29900, promo=False)), 'subscription_active')


class NoticeTests(APITestCase):
    def setUp(self):
        self.pro, self.start = plan(), plan('START', '99', 300, 1)
        self.org = make_org()
        self.org.plan = self.pro
        self.org.save()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.staff = make_user('s@cadrius.ia.br')
        self.staff.is_staff = True
        self.staff.save()
        self.staff.groups.add(Group.objects.get_or_create(name='Cadrius Financeiro')[0])   # área Financeiro (CAD-168)

    def test_equipe_cria_e_cliente_ve_conforme_plano_estado_e_periodo(self):
        now = timezone.now()
        self.client.force_authenticate(self.staff, token={'amr': 'mfa'})   # sessão com MFA (CAD-169)
        mk = lambda **kw: self.client.post(BASE + 'notices/', {'title': kw.pop('title'), 'body': 'texto', **kw}, format='json')  # noqa: E731
        self.assertEqual(mk(title='Todos').status_code, 201)
        mk(title='Só START', audience_tiers=['START'])
        mk(title='Só PRO', audience_tiers=['PRO'])
        mk(title='Só inadimplentes', audience_statuses=['past_due'])
        mk(title='Futuro', starts_at=(now + timedelta(days=2)).isoformat())
        mk(title='Vencido', ends_at=(now - timedelta(days=2)).isoformat())
        mk(title='Desligado', is_active=False)
        self.client.force_authenticate(self.owner)
        titles = sorted(n['title'] for n in self.client.get('/api/billing/notices/').data)
        self.assertEqual(titles, ['Só PRO', 'Todos'])
        self.org.subscription_status, self.org.past_due_since = 'past_due', now
        self.org.save()
        titles = sorted(n['title'] for n in self.client.get('/api/billing/notices/').data)
        self.assertEqual(titles, ['Só PRO', 'Só inadimplentes', 'Todos'])


class WeightsAndSummaryTests(APITestCase):
    def setUp(self):
        self.staff = make_user('s@cadrius.ia.br')
        self.staff.is_staff = True
        self.staff.save()
        self.staff.groups.add(Group.objects.get_or_create(name='Cadrius Financeiro')[0])   # área Financeiro (CAD-168)
        self.client.force_authenticate(self.staff, token={'amr': 'mfa'})   # sessão com MFA (CAD-169)

    def test_pesos_padrao_editaveis_e_credits_for(self):
        self.assertEqual(credits_for('draft_petition'), 15)       # padrão da análise, mesmo sem registro
        rows = self.client.get(BASE + 'credit-weights/').data      # cria os padrões
        self.assertIn('extraction', [r['operation'] for r in rows])
        row = next(r for r in rows if r['operation'] == 'draft_petition')
        self.assertEqual(self.client.patch(f"{BASE}credit-weights/{row['id']}/", {'credits': 20}, format='json').status_code, 200)
        self.assertEqual(credits_for('draft_petition'), 20)
        CreditWeight.objects.filter(operation='draft_petition').update(is_active=False)
        self.assertEqual(credits_for('draft_petition'), 15)
        self.assertEqual(credits_for('operacao_desconhecida'), 1)
        self.assertEqual(self.client.post(BASE + 'credit-weights/', {}, format='json').status_code, 405)

    def test_resumo(self):
        pro = plan()
        now = timezone.now()
        Organization.objects.create(name='A', plan=pro, stripe_subscription_id='sub_a')                      # paga
        Organization.objects.create(name='B', plan=pro, stripe_subscription_id='sub_b')                      # paga
        Organization.objects.create(name='C', plan=pro, subscription_status='trialing', trial_ends_at=now + timedelta(days=3))
        Organization.objects.create(name='D', plan=pro, subscription_status='past_due', past_due_since=now)
        org = Organization.objects.first()
        CreditLot.objects.create(organization=org, credits_total=200, credits_remaining=200, expires_at=now + timedelta(days=300),
                                 stripe_session_id='cs_1', amount_paid_cents=5900)
        data = self.client.get(BASE + 'summary/').data
        self.assertEqual(data['assinantes_pagantes'], 2)
        self.assertEqual(data['mrr_tabela_brl'], '598.00')
        self.assertEqual(data['ticket_medio_brl'], '299.00')
        self.assertEqual(data['trials_terminando_em_7_dias'], 1)
        self.assertEqual(data['organizacoes_por_estado']['past_due'], 1)
        self.assertEqual(data['pacotes_30d'], {'receita_brl': '59.0', 'creditos_vendidos': 200})
