from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from billing.models import SubscriptionPlan

User = get_user_model()


class PlansListTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='billing@example.com',
            email='billing@example.com',
            password='strong-password-123',
        )
        self.starter = SubscriptionPlan.objects.create(
            name='Starter',
            tier='FREE',
            price_brl=Decimal('0.00'),
            max_users=1,
            max_ai_extractions=10,
        )
        self.pro = SubscriptionPlan.objects.create(
            name='Professional',
            tier='PRO',
            price_brl=Decimal('99.00'),
            max_users=3,
            max_ai_extractions=1000,
        )
        SubscriptionPlan.objects.create(
            name='Legacy',
            tier='START',
            price_brl=Decimal('49.00'),
            max_users=2,
            max_ai_extractions=100,
            is_active=False,
        )

    def test_list_plans_authenticated(self):
        url = reverse('billing-plans')
        self.client.force_authenticate(user=self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

        starter = response.data[0]
        self.assertEqual(starter['id'], self.starter.id)
        self.assertEqual(starter['name'], 'Starter')
        self.assertEqual(starter['price'], 'Grátis')
        self.assertEqual(starter['description'], 'Limite de 10 documentos/mês')
        self.assertEqual(starter['features'], [])

        pro = response.data[1]
        self.assertEqual(pro['id'], self.pro.id)
        self.assertEqual(pro['name'], 'Professional')
        self.assertEqual(pro['price'], 'R$ 99')
        self.assertEqual(pro['description'], '')
        self.assertEqual(
            pro['features'],
            [
                '1.000 créditos',
                'Gestão de Tarefas',
                'Até 3 usuários',
                'Integrações premium',
            ],
        )

    def test_list_plans_unauthenticated(self):
        response = self.client.get(reverse('billing-plans'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)


class CurrentPlanTests(APITestCase):
    def setUp(self):
        from datetime import date

        from accounts.models import Organization, OrganizationMembership

        self.free = SubscriptionPlan.objects.create(
            name='Free',
            tier='FREE',
            price_brl=Decimal('0.00'),
            max_users=1,
            max_ai_extractions=100,
        )
        self.pro = SubscriptionPlan.objects.create(
            name='Pro',
            tier='PRO',
            price_brl=Decimal('500.00'),
            max_users=10,
            max_ai_extractions=100,
        )
        self.org = Organization.objects.create(
            name='Escritório Plano',
            plan=self.pro,
            next_billing_date=date(2026, 11, 1),
        )
        self.user = User.objects.create_user(
            username='plan@example.com',
            email='plan@example.com',
            password='strong-password-123',
        )
        OrganizationMembership.objects.create(user=self.user, organization=self.org, role='OWNER')

    def test_current_plan(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('billing-current-plan'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['plano']['name'], 'Pro')
        self.assertEqual(response.data['plano']['price'], 'R$ 500')
        self.assertEqual(
            response.data['plano']['features'],
            ['100 créditos', 'Gestão de Tarefas', 'Até 10 usuários', 'Integrações premium'],
        )
        self.assertEqual(response.data['status'], 'ativo')
        self.assertEqual(response.data['proxima_cobranca'], '2026-11-01')
        self.assertEqual([p['name'] for p in response.data['outros_planos']], ['Free'])

    def test_current_plan_without_organization(self):
        outsider = User.objects.create_user(
            username='noorg@example.com',
            email='noorg@example.com',
            password='strong-password-123',
        )
        self.client.force_authenticate(user=outsider)
        response = self.client.get(reverse('billing-current-plan'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_current_plan_unauthenticated(self):
        response = self.client.get(reverse('billing-current-plan'))
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
