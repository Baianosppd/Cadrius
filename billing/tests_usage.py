"""CAD-225: o uso de créditos aparece nas telas (plano, banner do teste e equipe) e as triagens com IA contam."""
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from accounts.models import Organization
from aigov.models import AIActionLog
from billing.credits import charge, consume_credit
from billing.models import CreditWeight, SubscriptionPlan
from cadrius.tests_security import make_user


class UsageShownTests(APITestCase):
    def setUp(self):
        plan = SubscriptionPlan.objects.create(name='Pro', tier='PRO', price_brl=Decimal('299'), max_users=5, max_ai_extractions=100)
        self.org = Organization.objects.create(name='Org', plan=plan, subscription_status='active')
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.member = make_user('m@example.com', self.org, role='MEMBER')

    def test_plano_mostra_usado_e_restante(self):
        consume_credit(self.org, user_id=self.member.pk, amount=7)
        self.client.force_authenticate(self.owner)
        a = self.client.get('/api/billing/plans/current/').data['assinatura']
        self.assertEqual(a['creditos_usados_mes'], 7)
        self.assertEqual(a['creditos_restantes'], a['creditos_mensais'] - 7)

    def test_equipe_mostra_uso_por_pessoa_e_por_atividade(self):
        consume_credit(self.org, user_id=self.member.pk, amount=3)
        AIActionLog.objects.create(organization_id=self.org.pk, user_ref=str(self.member.pk), kind='assistant', provider='ANTHROPIC',
                                   created_at=timezone.now())
        self.client.force_authenticate(self.owner)
        rows = {r['email']: r for r in self.client.get('/api/v1/teams/members/').json()}
        self.assertEqual(rows['m@example.com']['creditos_usados'], 3)
        resumo = self.client.get('/api/v1/teams/credits/').data
        self.assertEqual(resumo['creditos_usados'], 3)
        self.assertEqual(resumo['uso_por_atividade'][0]['atividade'], 'assistant')

    def test_charge_respeita_peso_configurado(self):
        self.assertEqual(charge(self.org, 'triage'), (True, ''))          # padrão 0: não cobra
        CreditWeight.objects.update_or_create(operation='triage', defaults={'label': 'Triagem', 'credits': 2})
        charge(self.org, 'triage', user_id=self.member.pk)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get('/api/v1/teams/credits/').data['creditos_usados'], 2)
