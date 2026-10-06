"""CAD-224: cupom na abertura do plano (cadastro), dias extras de teste e desconto reservado para o 1º pagamento."""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts import tests as acc_tests
from billing.models import Promotion, PromotionRedemption, SubscriptionPlan


@override_settings(STRIPE_SECRET_KEY='sk_test_x')
class SignupCouponTests(APITestCase):
    VALID_CPF = acc_tests.RegistrationTests.VALID_CPF
    VALID_CNPJ = acc_tests.RegistrationTests.VALID_CNPJ
    OTHER_CPF = acc_tests.RegistrationTests.OTHER_CPF

    def setUp(self):
        cache.clear()
        self.plan = SubscriptionPlan.objects.create(name='Pro', tier='PRO', price_brl=Decimal('199.00'), max_users=3, max_ai_extractions=50)
        self.trial = Promotion.objects.create(code='TESTE30', name='30 dias', kind='trial', value=30)
        self.disc = Promotion.objects.create(code='LANCA20', name='Lançamento', kind='percent', value=20)

    _individual_payload = acc_tests.RegistrationTests._individual_payload
    _company_payload = acc_tests.RegistrationTests._company_payload

    def register(self, **kw):
        return self.client.post('/api/v1/auth/register/', self._individual_payload(**kw), format='json')

    def test_cupom_invalido_barra_o_cadastro(self):
        res = self.register(cupom='NAOEXISTE')
        self.assertEqual(res.status_code, 400)
        self.assertIn('cupom', res.data)

    def test_dias_extras_aplicam_no_cadastro(self):
        res = self.register(cupom='teste30')
        self.assertEqual(res.status_code, 201, res.data)
        from accounts.models import Organization
        org = Organization.objects.get(name='Maria Silva Santos')
        self.assertGreater((org.trial_ends_at - timezone.now()).days, 30)
        self.assertTrue(PromotionRedemption.objects.filter(promotion=self.trial, organization=org).exists())

    def test_desconto_fica_reservado_e_vai_no_checkout(self):
        res = self.client.post('/api/v1/auth/register/empresa/', self._company_payload(cupom='LANCA20'), format='json')
        self.assertEqual(res.status_code, 201, res.data)
        from accounts.models import Organization, OrganizationMembership
        org = Organization.objects.get(nome_fantasia='Silva Advocacia')
        self.assertEqual(org.pending_promotion, self.disc)
        owner = OrganizationMembership.objects.get(organization=org).user
        self.client.force_authenticate(owner)
        self.assertEqual(self.client.get('/api/v1/auth/user/').data['organization']['cupom_pendente']['codigo'], 'LANCA20')
        session = mock.Mock(url='https://checkout.stripe.com/x')
        with mock.patch('billing.views.ensure_stripe_coupon', return_value='co_1'), \
                mock.patch('billing.views.stripe.checkout.Session.create', return_value=session) as create:
            res = self.client.post('/api/billing/checkout/', {'plan_id': self.plan.pk}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(create.call_args.kwargs['discounts'], [{'coupon': 'co_1'}])
        self.assertEqual(create.call_args.kwargs['metadata']['promo_id'], str(self.disc.pk))

    def test_cupom_de_teste_pelo_perfil_e_nao_no_pagamento(self):
        self.register()
        from accounts.models import Organization, OrganizationMembership
        org = Organization.objects.get(name='Maria Silva Santos')
        self.client.force_authenticate(OrganizationMembership.objects.get(organization=org).user)
        before = org.trial_ends_at
        ok = self.client.post('/api/billing/promotions/redeem/', {'code': 'TESTE30'}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        org.refresh_from_db()
        self.assertGreater(org.trial_ends_at, before)
        again = self.client.post('/api/billing/promotions/redeem/', {'code': 'TESTE30'}, format='json')
        self.assertEqual(again.status_code, 400)
        wrong = self.client.post('/api/billing/promotions/redeem/', {'code': 'LANCA20'}, format='json')
        self.assertEqual(wrong.status_code, 400)
        with mock.patch('billing.views.stripe.checkout.Session.create') as create:
            res = self.client.post('/api/billing/checkout/', {'plan_id': self.plan.pk, 'promo_code': 'TESTE30'}, format='json')
        self.assertEqual(res.status_code, 400)
        create.assert_not_called()

    @override_settings(STRIPE_SECRET_KEY='')
    def test_checkout_sem_chave_do_stripe_responde_503_claro(self):
        res = self.register()
        self.assertEqual(res.status_code, 201, res.data)
        from accounts.models import OrganizationMembership
        owner = OrganizationMembership.objects.get(organization__name='Maria Silva Santos').user
        self.client.force_authenticate(owner)
        with mock.patch('billing.views.stripe.checkout.Session.create') as create:
            res = self.client.post('/api/billing/checkout/', {'plan_id': self.plan.pk}, format='json')
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.data['code'], 'payments_not_configured')
        create.assert_not_called()
