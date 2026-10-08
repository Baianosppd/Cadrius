"""CAD-232: cada escritório usa só os créditos do seu plano + o que comprou à parte.

- Gratuito / teste: 30 créditos no total (não renova na virada do mês).
- Plano pago ativo: a quantidade do plano por mês + pacotes avulsos comprados (com validade).
- Sem saldo: nenhuma IA roda, venha de onde vier (a trava fica na governança, antes de chamar o provedor).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Organization
from aigov.guard import AIBlocked, run_guarded
from billing.credits import consume_credit, usage_summary
from billing.models import AIUsageLog, CreditLot, SubscriptionPlan
from cadrius.tests_security import make_user


def plan(tier, credits, price):
    return SubscriptionPlan.objects.create(name=tier.title(), tier=tier, price_brl=Decimal(price), max_users=5,
                                           max_ai_extractions=credits)


@override_settings(TRIAL_CREDITS=30)
class PlanLimitTests(TestCase):
    def setUp(self):
        self.free = plan('FREE', 30, '0')
        self.pro = plan('PRO', 1500, '299')

    def org(self, p, **kw):
        return Organization.objects.create(name='Escritório', plan=p, **kw)

    def spend(self, org, n):
        ok = 0
        for _ in range(n):
            ok += consume_credit(org)[0]
        return ok

    def test_gratuito_usa_so_30_no_total_mesmo_virando_o_mes(self):
        org = self.org(self.free, subscription_status='trialing', trial_ends_at=timezone.now() + timedelta(days=10))
        AIUsageLog.objects.create(organization=org, billing_cycle_month=date(2000, 1, 1), extractions_count=20)  # mês passado
        self.assertEqual(self.spend(org, 15), 10)                 # sobram só 10 dos 30
        self.assertEqual(usage_summary(org)['creditos_restantes'], 0)
        with self.assertRaises(AIBlocked) as ctx:                  # e nenhuma IA roda depois disso
            run_guarded(organization=org, kind='assistant', provider='GROQ', fn=lambda: 'x')
        self.assertEqual(ctx.exception.code, 'no_credits')

    def test_plano_pago_escolhido_no_cadastro_vale_30_ate_pagar(self):
        org = self.org(self.pro, subscription_status='trialing', trial_ends_at=timezone.now() + timedelta(days=10))
        self.assertEqual(self.spend(org, 40), 30)

    def test_plano_pago_ativo_usa_o_plano_e_depois_os_avulsos(self):
        org = self.org(plan('START', 5, '99'), subscription_status='active')
        CreditLot.objects.create(organization=org, credits_total=3, credits_remaining=3, stripe_session_id='cs_x',
                                 expires_at=timezone.now() + timedelta(days=30), amount_paid_cents=1000)
        CreditLot.objects.create(organization=org, credits_total=50, credits_remaining=50, stripe_session_id='cs_old',
                                 expires_at=timezone.now() - timedelta(days=1), amount_paid_cents=1000)   # vencido
        self.assertEqual(self.spend(org, 10), 8)                  # 5 do plano + 3 avulsos; o lote vencido não conta
        self.assertFalse(consume_credit(org)[0])

    def test_plano_pago_renova_no_mes_seguinte(self):
        org = self.org(self.pro, subscription_status='active')
        AIUsageLog.objects.create(organization=org, billing_cycle_month=date(2000, 1, 1), extractions_count=1500)
        self.assertTrue(consume_credit(org)[0])                   # o mês passado não pesa no atual

    def test_teste_vencido_ou_assinatura_pausada_nao_usa_ia(self):
        org = self.org(self.free, subscription_status='trialing', trial_ends_at=timezone.now() - timedelta(days=1))
        self.assertFalse(consume_credit(org)[0])
        with self.assertRaises(AIBlocked):
            run_guarded(organization=org, kind='assistant', provider='GROQ', fn=lambda: 'x')

    def test_cota_do_membro_continua_valendo(self):
        org = self.org(self.pro, subscription_status='active')
        user = make_user('m@x.com', org)
        m = user.memberships.get()
        m.credit_limit = 2
        m.save()
        self.assertEqual(sum(consume_credit(org, user_id=user.pk)[0] for _ in range(3)), 2)
