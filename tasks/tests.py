from datetime import datetime

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from django.contrib.auth import get_user_model

from tasks.models import UserTask

User = get_user_model()


class UserTaskAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='taskuser@example.com',
            email='taskuser@example.com',
            password='strong-password-123',
            first_name='Task',
            last_name='User',
        )
        self.other_user = User.objects.create_user(
            username='other@example.com',
            email='other@example.com',
            password='strong-password-123',
        )

    def test_create_task(self):
        url = reverse('task-list')
        self.client.force_authenticate(user=self.user)
        scheduled_at = timezone.make_aware(datetime(2025, 6, 10, 9, 0))

        with self.settings(TIME_ZONE='America/Sao_Paulo'):
            response = self.client.post(
                url,
                {
                    'titulo': 'Responder petição',
                    'descricao': 'Descrição da tarefa',
                    'dataHorario': scheduled_at.isoformat(),
                    'prioridade': 'alta',
                    'responsavel': str(self.user.id),
                    'sincronizar': False,
                },
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['description'], 'Responder petição')
        self.assertEqual(response.data['priority'], 'alta')
        self.assertEqual(response.data['completed'], False)
        self.assertTrue(UserTask.objects.filter(titulo='Responder petição').exists())

    def test_list_tasks_for_today(self):
        today = timezone.localdate()
        scheduled_at = timezone.make_aware(
            datetime.combine(today, datetime.min.time().replace(hour=9, minute=0)),
        )
        UserTask.objects.create(
            titulo='Audiência',
            descricao='Preparar documentos',
            scheduled_at=scheduled_at,
            priority='alta',
            responsavel=self.user,
        )
        UserTask.objects.create(
            titulo='Outro user',
            scheduled_at=scheduled_at,
            priority='media',
            responsavel=self.other_user,
        )

        url = reverse('task-list')
        self.client.force_authenticate(user=self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['description'], 'Audiência')
        self.assertEqual(response.data[0]['time'], '09:00')
        self.assertEqual(response.data[0]['priority'], 'alta')

    def test_list_tasks_unauthenticated(self):
        url = reverse('task-list')
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def _create_today_task(self, user=None, titulo='Audiência'):
        today = timezone.localdate()
        scheduled_at = timezone.make_aware(
            datetime.combine(today, datetime.min.time().replace(hour=9, minute=0)),
        )
        return UserTask.objects.create(
            titulo=titulo,
            scheduled_at=scheduled_at,
            priority='alta',
            responsavel=user or self.user,
        )

    def test_patch_task_completed(self):
        task = self._create_today_task()
        url = reverse('task-detail', kwargs={'pk': task.pk})
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(url, {'completed': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['completed'])

        task.refresh_from_db()
        self.assertTrue(task.completed)

        response = self.client.patch(url, {'completed': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['completed'])

    def test_patch_task_other_user_forbidden(self):
        task = self._create_today_task(user=self.other_user)
        url = reverse('task-detail', kwargs={'pk': task.pk})
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(url, {'completed': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
