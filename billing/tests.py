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
