from datetime import date, datetime, timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from django.contrib.auth import get_user_model

from accounts.models import Organization, OrganizationMembership
from billing.models import SubscriptionPlan
from core.activities import format_relative_time, recent_activities_for_user
from emails.models import EmailMessage, MailBox
from workflows.models import ExecutionLog, Workflow

User = get_user_model()


class ActivitiesTests(APITestCase):
    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name='Plano Teste',
            tier='FREE',
            price_brl=0,
            max_users=5,
            max_ai_extractions=100,
        )
        self.org = Organization.objects.create(name='Escritório Teste', plan=self.plan)
        self.user = User.objects.create_user(
            username='activity@example.com',
            email='activity@example.com',
            password='strong-password-123',
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role='OWNER',
        )
        self.workflow = Workflow.objects.create(
            name='Notificar Cliente',
            organization=self.org,
        )
        self.mailbox = MailBox.objects.create(
            user=self.user,
            name='Caixa Teste',
            imap_host='imap.example.com',
            username='user',
            password='pass',
        )

    def test_activities_empty(self):
        self.assertEqual(recent_activities_for_user(self.user), [])

    def test_document_activity(self):
        EmailMessage.objects.create(
            mailbox=self.mailbox,
            message_id='msg-1',
            subject='Petição Inicial',
            sender='tribunal@example.com',
            received_at=timezone.now(),
            body_text='Corpo',
            is_dispatched=True,
        )

        activities = recent_activities_for_user(self.user)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]['title'], 'Documento analisado com sucesso')
        self.assertEqual(activities[0]['description'], 'Petição Inicial foi processada.')
        self.assertEqual(activities[0]['type'], 'success')

    def test_execution_success_and_prazo(self):
        ExecutionLog.objects.create(
            workflow=self.workflow,
            triggered_by=self.user,
            status='SUCCESS',
            trigger_payload={
                'numero_processo': '0001234-56.2025.8.09.0001',
                'prazo_fatal': '2025-06-20',
            },
        )

        activities = recent_activities_for_user(self.user)
        self.assertEqual(len(activities), 2)
        titles = {item['title'] for item in activities}
        self.assertIn('Prazo identificado', titles)
        self.assertIn('Automação executada', titles)
        prazo = next(item for item in activities if item['title'] == 'Prazo identificado')
        self.assertIn('2025-06-20', prazo['description'])
        self.assertEqual(prazo['type'], 'warning')

    def test_execution_failed(self):
        ExecutionLog.objects.create(
            workflow=self.workflow,
            triggered_by=self.user,
            status='FAILED',
            error_message='Timeout na API externa',
        )

        activities = recent_activities_for_user(self.user)
        self.assertEqual(activities[0]['type'], 'error')
        self.assertIn('Timeout', activities[0]['description'])

    def test_format_relative_time_minutes(self):
        value = timezone.now() - timedelta(minutes=20)
        self.assertEqual(format_relative_time(value), 'Há 20 minutos')

    def test_activities_endpoint(self):
        EmailMessage.objects.create(
            mailbox=self.mailbox,
            message_id='msg-2',
            subject='Petição Inicial',
            sender='tribunal@example.com',
            received_at=timezone.now(),
            body_text='Corpo',
            is_dispatched=True,
        )
        url = reverse('activities')
        self.client.force_authenticate(user=self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], 'Documento analisado com sucesso')

    def test_activities_unauthenticated(self):
        response = self.client.get(reverse('activities'))
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
