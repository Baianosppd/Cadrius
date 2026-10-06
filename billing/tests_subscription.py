"""CAD-119: plano pago só vale depois do pagamento; carência de inadimplência; créditos avulsos; webhook idempotente."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Organization
from audit.models import AuditEvent
from billing import entitlements as ent
from billing.credits import check_credit_available, consume_credit
from billing.models import CreditLot, CreditPack, SubscriptionPlan
from billing.stripe_sync import apply_event
from cadrius.tests_security import legal_acceptance, make_user


def make_paid_plan(price='299', credits=1500, users=5, tier='PRO'):
    return SubscriptionPlan.objects.create(name=tier.title(), tier=tier, price_brl=Decimal(price), max_users=users,
                                           max_ai_extractions=credits)


def org_with(plan, **kw):
    return Organization.objects.create(name='Org', plan=plan, **kw)


class RegistrationStartsTrialTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.plan = make_paid_plan()

    def payload(self, **kw):
        return {'nome_completo': 'Maria Silva Santos', 'cpf': '529.982.247-25', 'email': 'maria@email.com',
                'senha': 'Cadrius#2026', 'plano_id': self.plan.id, **legal_acceptance(), **kw}

    def test_plano_pago_escolhido_no_cadastro_nao_libera_os_limites_do_plano(self):
        resp = self.client.post('/api/v1/auth/register/', self.payload(), format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        org = Organization.objects.get(name='Maria Silva Santos')
        self.assertEqual(org.plan_id, self.plan.pk)            # plano ESCOLHIDO
        self.assertEqual(org.subscription_status, 'trialing')  # mas em trial
        self.assertIsNotNone(org.trial_ends_at)
        self.assertEqual(ent.effective_monthly_credits(org), 30)   # TRIAL_CREDITS, não 1.500
        self.assertEqual(ent.effective_max_users(org), 3)          # TRIAL_MAX_USERS, não 5


class EntitlementsTests(TestCase):
    def setUp(self):
        self.plan = make_paid_plan()

    def test_estados_e_limites(self):
        now = timezone.now()
        org = org_with(self.plan)  # legado/semeado: ativo
        self.assertEqual((ent.effective_status(org), ent.effective_monthly_credits(org)), ('active', 1500))

        org.subscription_status, org.trial_ends_at = 'trialing', now + timedelta(days=3)
        self.assertEqual((ent.effective_status(org), ent.effective_monthly_credits(org)), ('trialing', 30))
        org.trial_ends_at = now - timedelta(seconds=1)  # trial vencido sem pagar
        self.assertEqual((ent.effective_status(org), ent.effective_monthly_credits(org), ent.ai_enabled(org)),
                         ('restricted', 0, False))

    def test_carencia_da_inadimplencia(self):
        now = timezone.now()
        org = org_with(self.plan, subscription_status='past_due')
        for days, expected, credits in ((0, 'past_due', 1500), (7, 'past_due', 1500), (8, 'restricted', 0),
                                        (14, 'restricted', 0), (15, 'suspended', 0), (30, 'suspended', 0),
                                        (31, 'canceled', 0)):
            org.past_due_since = now - timedelta(days=days, hours=1)
            self.assertEqual(ent.effective_status(org, now), expected, f'dia {days}')
            self.assertEqual(ent.effective_monthly_credits(org, now), credits, f'dia {days}')

    def test_sem_convites_quando_pausado(self):
        org = org_with(self.plan, subscription_status='canceled')
        self.assertEqual(ent.effective_max_users(org), 0)


class CreditConsumptionTests(TestCase):
    def setUp(self):
        self.plan = make_paid_plan(credits=3)
        self.org = org_with(self.plan)

    def lot(self, credits, days=365, session='cs_1'):
        return CreditLot.objects.create(organization=self.org, credits_total=credits, credits_remaining=credits,
                                        expires_at=timezone.now() + timedelta(days=days), stripe_session_id=session)

    def test_usa_primeiro_o_plano_depois_os_avulsos(self):
        lot = self.lot(2)
        for _ in range(3):
            self.assertEqual(consume_credit(self.org), (True, ''))
        lot.refresh_from_db()
        self.assertEqual(lot.credits_remaining, 2)           # o plano (3) saiu primeiro
        self.assertTrue(consume_credit(self.org)[0])
        self.assertTrue(consume_credit(self.org)[0])
        lot.refresh_from_db()
        self.assertEqual(lot.credits_remaining, 0)
        self.assertFalse(consume_credit(self.org)[0])        # acabou tudo
        self.assertFalse(check_credit_available(self.org)[0])

    def test_lote_mais_proximo_do_vencimento_sai_primeiro_e_vencido_nao_conta(self):
        late, soon = self.lot(5, days=300, session='a'), self.lot(5, days=10, session='b')
        self.lot(50, days=-1, session='c')                    # vencido
        for _ in range(3):
            consume_credit(self.org)                          # esgota o plano
        consume_credit(self.org, amount=2)
        soon.refresh_from_db(), late.refresh_from_db()
        self.assertEqual((soon.credits_remaining, late.credits_remaining), (3, 5))
        self.assertFalse(consume_credit(self.org, amount=20)[0])  # só 8 válidos

    def test_ia_pausada_bloqueia_mesmo_com_creditos_avulsos(self):
        self.lot(100)
        self.org.subscription_status = 'canceled'
        self.assertEqual(consume_credit(self.org), (False, ent.PAUSED_MESSAGE))
        self.assertEqual(check_credit_available(self.org), (False, ent.PAUSED_MESSAGE))

    def test_cota_do_membro_continua_valendo_para_credito_avulso(self):
        self.lot(10)
        user = make_user('m@example.com', self.org)
        from accounts.models import OrganizationMembership
        membership = OrganizationMembership.objects.get(user=user, organization=self.org)
        membership.credit_limit = 1
        membership.save()
        self.assertTrue(consume_credit(self.org, user_id=user.pk)[0])
        self.assertEqual(consume_credit(self.org, user_id=user.pk)[1], 'Limite de créditos individual atingido.')


class StripeSyncTests(TestCase):
    def setUp(self):
        self.plan = make_paid_plan(price='299')
        self.org = org_with(self.plan, subscription_status='trialing', trial_ends_at=timezone.now() + timedelta(days=5))
        self.pack = CreditPack.objects.create(name='200', credits=200, price_brl=Decimal('59'))

    def session(self, **over):
        base = {'id': 'cs_test_1', 'client_reference_id': str(self.org.pk), 'payment_status': 'paid', 'amount_total': 29900,
                'customer': 'cus_1', 'subscription': 'sub_1', 'metadata': {'kind': 'subscription', 'plan_id': str(self.plan.pk)}}
        base.update(over)
        return {'type': 'checkout.session.completed', 'data': {'object': base}}

    def test_pagamento_confirmado_ativa_e_promove_o_plano(self):
        other = make_paid_plan(price='99', credits=300, users=1, tier='START')
        self.org.plan = other           # tinha escolhido o outro plano no cadastro
        self.org.save()
        self.assertEqual(apply_event(self.session()), 'subscription_active')
        self.org.refresh_from_db()
        self.assertEqual((self.org.plan_id, self.org.subscription_status, self.org.stripe_subscription_id),
                         (self.plan.pk, 'active', 'sub_1'))
        self.assertEqual(ent.effective_monthly_credits(self.org), 1500)
        self.assertTrue(AuditEvent.objects.filter(action='billing.payment_confirmed', outcome='success').exists())

    def test_nao_promove_sem_pagamento_ou_com_valor_diferente_ou_plano_adulterado(self):
        for ev, expected in ((self.session(payment_status='unpaid'), 'ignored:not_paid'),
                             (self.session(amount_total=100), 'ignored:plan_mismatch'),
                             (self.session(metadata={'kind': 'subscription', 'plan_id': '99999'}), 'ignored:plan_mismatch'),
                             (self.session(client_reference_id='00000000-0000-0000-0000-000000000000'), 'ignored:unknown_org')):
            self.assertEqual(apply_event(ev), expected)
        self.org.refresh_from_db()
        self.assertEqual(self.org.subscription_status, 'trialing')
        self.assertEqual(ent.effective_monthly_credits(self.org), 30)

    def test_compra_de_creditos_e_idempotente_e_confere_valor(self):
        ev = self.session(id='cs_pack_1', amount_total=5900, metadata={'kind': 'credit_pack', 'pack_id': str(self.pack.pk)})
        self.assertEqual(apply_event(ev), 'credits_added')
        self.assertEqual(apply_event(ev), 'duplicate')       # webhook reenviado
        self.assertEqual(CreditLot.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(ent.purchased_credits_balance(self.org), 200)
        bad = self.session(id='cs_pack_2', amount_total=100, metadata={'kind': 'credit_pack', 'pack_id': str(self.pack.pk)})
        self.assertEqual(apply_event(bad), 'ignored:pack_mismatch')
        self.assertEqual(ent.purchased_credits_balance(self.org), 200)

    def test_falha_de_cobranca_abre_carencia_e_pagamento_a_encerra(self):
        apply_event(self.session())
        failed = {'type': 'invoice.payment_failed', 'data': {'object': {'subscription': 'sub_1'}}}
        self.assertEqual(apply_event(failed), 'past_due')
        self.org.refresh_from_db()
        self.assertEqual(self.org.subscription_status, 'past_due')
        first = self.org.past_due_since
        apply_event(failed)                                    # nova tentativa não reinicia a carência
        self.org.refresh_from_db()
        self.assertEqual(self.org.past_due_since, first)
        paid = {'type': 'invoice.payment_succeeded', 'data': {'object': {
            'parent': {'subscription_details': {'subscription': 'sub_1'}},
            'lines': {'data': [{'period': {'end': 1893456000}}]}}}}
        self.assertEqual(apply_event(paid), 'renewed')
        self.org.refresh_from_db()
        self.assertEqual((self.org.subscription_status, self.org.past_due_since), ('active', None))
        self.assertEqual(self.org.current_period_end.year, 2030)

    def test_assinatura_cancelada_e_eventos_desconhecidos(self):
        apply_event(self.session())
        self.assertEqual(apply_event({'type': 'customer.subscription.deleted', 'data': {'object': {'id': 'sub_1'}}}), 'canceled')
        self.org.refresh_from_db()
        self.assertEqual(ent.effective_status(self.org), 'canceled')
        self.assertEqual(apply_event({'type': 'customer.created', 'data': {'object': {}}}), 'ignored:event_type')
        self.assertEqual(apply_event({'type': 'invoice.payment_failed', 'data': {'object': {'subscription': 'sub_x'}}}),
                         'ignored:unknown_subscription')


@override_settings(STRIPE_WEBHOOK_SECRET='whsec_test', FRONTEND_URL='https://app.example.com', STRIPE_SECRET_KEY='sk_test_x')
class BillingApiTests(APITestCase):
    def setUp(self):
        self.plan = make_paid_plan()
        self.org = org_with(self.plan)
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.member = make_user('m@example.com', self.org, role='MEMBER')
        self.pack = CreditPack.objects.create(name='200', credits=200, price_brl=Decimal('59'))

    def test_checkout_grava_metadados_do_plano_e_do_escritorio(self):
        self.client.force_authenticate(self.owner)
        with mock.patch('billing.views.stripe.checkout.Session.create') as create:
            create.return_value = mock.Mock(url='https://stripe.test/c')
            resp = self.client.post('/api/billing/checkout/', {'plan_id': self.plan.pk}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['client_reference_id'], str(self.org.pk))
        self.assertEqual(kwargs['metadata'], {'kind': 'subscription', 'plan_id': str(self.plan.pk)})
        self.assertEqual(kwargs['subscription_data']['metadata']['plan_id'], str(self.plan.pk))

    def test_checkout_recusa_plano_gratuito_e_inativo(self):
        free = SubscriptionPlan.objects.create(name='F', tier='FREE', price_brl=0, max_users=1, max_ai_extractions=30)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post('/api/billing/checkout/', {'plan_id': free.pk}, format='json').status_code, 400)
        self.plan.is_active = False
        self.plan.save()
        self.assertEqual(self.client.post('/api/billing/checkout/', {'plan_id': self.plan.pk}, format='json').status_code, 400)

    def test_compra_de_creditos_so_para_gestor_e_com_ia_ativa(self):
        with mock.patch('billing.views.stripe.checkout.Session.create') as create:
            create.return_value = mock.Mock(url='https://stripe.test/p')
            self.client.force_authenticate(self.member)
            self.assertEqual(self.client.post('/api/billing/credit-packs/checkout/', {'pack_id': self.pack.pk}, format='json').status_code, 403)
            self.client.force_authenticate(self.owner)
            resp = self.client.post('/api/billing/credit-packs/checkout/', {'pack_id': self.pack.pk}, format='json')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(create.call_args.kwargs['mode'], 'payment')
            self.assertEqual(create.call_args.kwargs['metadata'], {'kind': 'credit_pack', 'pack_id': str(self.pack.pk)})
            self.org.subscription_status = 'canceled'
            self.org.save()
            self.assertEqual(self.client.post('/api/billing/credit-packs/checkout/', {'pack_id': self.pack.pk}, format='json').status_code, 400)

    def test_webhook_com_assinatura_valida_aplica_e_invalida_e_recusada(self):
        event = {'type': 'checkout.session.completed', 'data': {'object': {
            'id': 'cs_9', 'client_reference_id': str(self.org.pk), 'payment_status': 'paid', 'amount_total': 29900,
            'subscription': 'sub_9', 'metadata': {'kind': 'subscription', 'plan_id': str(self.plan.pk)}}}}
        with mock.patch('billing.views.stripe.Webhook.construct_event', return_value=event):
            ok = self.client.post('/api/billing/webhook/', data=b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='x')
        self.assertEqual(ok.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.stripe_subscription_id, 'sub_9')
        import stripe
        with mock.patch('billing.views.stripe.Webhook.construct_event', side_effect=stripe.SignatureVerificationError('x', 'y')):
            bad = self.client.post('/api/billing/webhook/', data=b'{}', content_type='application/json', HTTP_STRIPE_SIGNATURE='x')
        self.assertEqual(bad.status_code, 400)

    def test_plano_atual_expoe_estado_da_assinatura_e_creditos_avulsos(self):
        CreditLot.objects.create(organization=self.org, credits_total=50, credits_remaining=40,
                                 expires_at=timezone.now() + timedelta(days=30), stripe_session_id='cs_x')
        self.client.force_authenticate(self.owner)
        data = self.client.get('/api/billing/plans/current/').data['assinatura']
        self.assertEqual((data['estado'], data['ia_ativa'], data['creditos_mensais'], data['creditos_avulsos']),
                         ('active', True, 1500, 40))
        resp = self.client.get('/api/billing/credit-packs/')
        self.assertEqual(resp.data[0]['credits'], 200)


class SeedPlansTests(TestCase):
    def test_sem_apply_nao_grava_e_com_apply_cria_sem_sobrescrever(self):
        out = StringIO()
        call_command('seed_plans', stdout=out)
        self.assertFalse(SubscriptionPlan.objects.exists())
        self.assertIn('Nada foi gravado', out.getvalue())
        call_command('seed_plans', '--apply', stdout=StringIO())
        self.assertEqual(SubscriptionPlan.objects.count(), 4)
        self.assertEqual(CreditPack.objects.count(), 3)
        SubscriptionPlan.objects.filter(tier='PRO').update(price_brl=Decimal('1'))
        call_command('seed_plans', '--apply', stdout=StringIO())
        self.assertEqual(SubscriptionPlan.objects.get(tier='PRO').price_brl, Decimal('1'))  # não sobrescreve sem --update
        call_command('seed_plans', '--apply', '--update', stdout=StringIO())
        self.assertEqual(SubscriptionPlan.objects.get(tier='PRO').price_brl, Decimal('299'))
