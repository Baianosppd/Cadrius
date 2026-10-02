from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organization, OrganizationMembership
from billing.models import SubscriptionPlan
from emails.models import EmailMessage, MailBox
from workflows.models import ExecutionLog, Workflow

from .models import Notification
from .services import (
    notify_automation_succeeded,
    notify_document_analyzed,
    notify_integration_failure,
    sync_deadline_notifications,
)

User = get_user_model()


class NotificationBaseTestCase(APITestCase):
    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name='Plano Notif',
            tier='PRO',
            price_brl=Decimal('0.00'),
            max_users=5,
            max_ai_extractions=100,
        )
        self.org = Organization.objects.create(name='Escritório Notif', plan=self.plan)
        self.owner = self._user('owner-notif@example.com', 'OWNER')
        self.admin = self._user('admin-notif@example.com', 'ADMIN')
        self.member = self._user('member-notif@example.com', 'MEMBER')
        self.other_member = self._user('other-notif@example.com', 'MEMBER')
        self.workflow = Workflow.objects.create(name='Avisar Cliente', organization=self.org)

    def _user(self, email, role):
        user = User.objects.create_user(username=email, email=email, password='strong-password-123')
        OrganizationMembership.objects.create(user=user, organization=self.org, role=role)
        return user

    def _recipients(self, title):
        return set(
            Notification.objects.filter(title=title).values_list('user__email', flat=True)
        )


class NotifyRecipientsTests(NotificationBaseTestCase):
    def test_actor_and_managers_receive(self):
        log = ExecutionLog.objects.create(
            workflow=self.workflow,
            triggered_by=self.member,
            status='SUCCESS',
            trigger_payload={'customer_name': 'Maria Santos'},
        )
        notify_automation_succeeded(log, 'WHATSAPP_EVOLUTION', self.member.id, log.trigger_payload)

        self.assertEqual(
            self._recipients('Nova automação concluída'),
            {'member-notif@example.com', 'owner-notif@example.com', 'admin-notif@example.com'},
        )
        notification = Notification.objects.filter(user=self.member).get()
        self.assertEqual(
            notification.description,
            'WhatsApp enviado automaticamente para o cliente Maria Santos.',
        )

    def test_same_event_is_not_duplicated(self):
        log = ExecutionLog.objects.create(workflow=self.workflow, triggered_by=self.member, status='SUCCESS')
        notify_automation_succeeded(log, 'WEBHOOK', self.member.id)
        notify_automation_succeeded(log, 'WEBHOOK', self.member.id)

        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)

    def test_integration_failure_resolves_organization_from_actor(self):
        notify_integration_failure(integration='Telegram', actor_id=self.member.id, dedupe_key='t:1')

        self.assertEqual(
            self._recipients('Falha na sincronização'),
            {'member-notif@example.com', 'owner-notif@example.com', 'admin-notif@example.com'},
        )
        notification = Notification.objects.filter(user=self.owner).get()
        self.assertEqual(notification.type, 'erro')
        self.assertEqual(notification.organization, self.org)

    def test_document_analyzed_mentions_prazo_only_when_extracted(self):
        mailbox = MailBox.objects.create(
            user=self.member,
            name='Caixa',
            imap_host='imap.example.com',
            username='u',
            password='p',
        )
        email = EmailMessage.objects.create(
            mailbox=mailbox,
            message_id='msg-1',
            subject='Petição Inicial - Caso Silva',
            sender='tribunal@example.com',
            received_at=timezone.now(),
            body_text='Corpo',
        )
        notify_document_analyzed(email, self.org, {'prazo_fatal': '2026-10-10'})

        notification = Notification.objects.filter(user=self.member).get()
        self.assertEqual(
            notification.description,
            'Petição Inicial - Caso Silva foi processado e os prazos foram extraídos.',
        )


@override_settings(MEDIA_ROOT='/tmp/cadrius-test-media')
class DocumentUploadNotificationTests(NotificationBaseTestCase):
    def test_upload_creates_notification(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.post(
            reverse('documentos-list'),
            {
                'nome': 'Contrato de Prestação de Serviços',
                'tipo': 'contrato',
                'status': 'pronto',
                'arquivo': SimpleUploadedFile('contrato.pdf', b'%PDF-1.4', content_type='application/pdf'),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        notification = Notification.objects.filter(user=self.member).get()
        self.assertEqual(notification.title, 'Novo documento carregado')
        self.assertEqual(
            notification.description,
            'Contrato de Prestação de Serviços foi enviado com sucesso.',
        )


class DeadlineNotificationTests(NotificationBaseTestCase):
    def _log(self, user, prazo, processo='1234.56.789'):
        return ExecutionLog.objects.create(
            workflow=self.workflow,
            triggered_by=user,
            status='SUCCESS',
            trigger_payload={'prazo_fatal': prazo.isoformat(), 'numero_processo': processo},
        )

    def test_creates_notification_inside_window(self):
        self._log(self.member, timezone.localdate() + timedelta(days=5))

        sync_deadline_notifications(self.member)

        notification = Notification.objects.get(user=self.member, type='prazo')
        self.assertEqual(notification.title, 'Prazo próximo identificado')
        self.assertEqual(notification.description, 'Prazo do processo 1234.56.789 vence em 5 dias.')

    def test_ignores_outside_window_and_past(self):
        self._log(self.member, timezone.localdate() + timedelta(days=6), processo='A')
        self._log(self.member, timezone.localdate() - timedelta(days=1), processo='B')

        sync_deadline_notifications(self.member)

        self.assertFalse(Notification.objects.filter(type='prazo').exists())

    def test_milestones_do_not_repeat(self):
        prazo = timezone.localdate() + timedelta(days=3)
        self._log(self.member, prazo)
        self._log(self.member, prazo)  # mesmo processo processado duas vezes

        sync_deadline_notifications(self.member)
        sync_deadline_notifications(self.member)

        self.assertEqual(Notification.objects.filter(user=self.member, type='prazo').count(), 1)

    def test_member_only_sees_own_deadlines_and_managers_see_all(self):
        self._log(self.other_member, timezone.localdate() + timedelta(days=1))

        sync_deadline_notifications(self.member)
        sync_deadline_notifications(self.owner)

        self.assertFalse(Notification.objects.filter(user=self.member, type='prazo').exists())
        notification = Notification.objects.get(user=self.owner, type='prazo')
        self.assertEqual(notification.description, 'Prazo do processo 1234.56.789 vence amanhã.')


class NotificationApiTests(NotificationBaseTestCase):
    def _create(self, user, title='Teste', **kwargs):
        return Notification.objects.create(user=user, organization=self.org, type='documento', title=title, **kwargs)

    def test_list_is_paginated_and_scoped_to_user(self):
        self._create(self.member, title='Minha')
        self._create(self.owner, title='Do owner')

        self.client.force_authenticate(user=self.member)
        response = self.client.get(reverse('notifications'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        item = response.data['results'][0]
        self.assertEqual(item['title'], 'Minha')
        self.assertFalse(item['read'])
        self.assertIn('time', item)
        self.assertIn('actionLabel', item)

    def test_unread_count_and_mark_read(self):
        first = self._create(self.member)
        self._create(self.member)
        self.client.force_authenticate(user=self.member)

        self.assertEqual(self.client.get(reverse('notifications-unread-count')).data, {'unread': 2})

        response = self.client.post(reverse('notifications-read', args=[first.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['read'])
        self.assertEqual(self.client.get(reverse('notifications-unread-count')).data, {'unread': 1})

    def test_mark_all_read(self):
        self._create(self.member)
        self._create(self.member)
        self.client.force_authenticate(user=self.member)

        response = self.client.post(reverse('notifications-read-all'))

        self.assertEqual(response.data, {'updated': 2})
        self.assertEqual(self.client.get(reverse('notifications-unread-count')).data, {'unread': 0})

    def test_cannot_mark_other_users_notification(self):
        others = self._create(self.owner)
        self.client.force_authenticate(user=self.member)

        response = self.client.post(reverse('notifications-read', args=[others.pk]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_old_notifications_are_purged_on_read(self):
        old = self._create(self.member, title='Antiga')
        Notification.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=91))
        self._create(self.member, title='Recente')
        self.client.force_authenticate(user=self.member)

        response = self.client.get(reverse('notifications'))

        self.assertEqual([n['title'] for n in response.data['results']], ['Recente'])
        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())

    def test_unauthenticated(self):
        response = self.client.get(reverse('notifications-unread-count'))
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
