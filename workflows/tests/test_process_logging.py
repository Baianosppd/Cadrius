from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Organization
from billing.models import SubscriptionPlan
from integrations.models import AppConnection
from workflows import tasks as workflow_tasks
from workflows.models import Action, ExecutionLog, Trigger, Workflow

User = get_user_model()


class ProcessWorkflowExecutionLoggingTests(TestCase):
    """CAD-059: erros do worker incluem execution_log_id para busca no Dozzle."""

    def setUp(self):
        plan = SubscriptionPlan.objects.create(
            name='Plano Teste', tier='FREE', price_brl=0, max_users=5, max_ai_extractions=100,
        )
        org = Organization.objects.create(name='Escritório Teste', plan=plan)
        user = User.objects.create_user(username='w@example.com', email='w@example.com', password='x-123456')
        connection = AppConnection.objects.create(user=user, name='Hook', app_name='WEBHOOK')
        self.workflow = Workflow.objects.create(name='WF', organization=org)
        Trigger.objects.create(workflow=self.workflow, connection=connection, event_type='manual')
        Action.objects.create(
            workflow=self.workflow,
            action_type='WEBHOOK',
            endpoint_url='https://example.com/hook',
            payload_template='{"a": 1}',
        )
        self.exec_log = ExecutionLog.objects.create(
            workflow=self.workflow, status='PENDING', trigger_payload={'x': 1},
        )

    def test_falha_http_regista_execution_log_id(self):
        with mock.patch.object(
            workflow_tasks, '_dispatch_action_execution',
            side_effect=requests.exceptions.ConnectionError('boom'),
        ), mock.patch.object(workflow_tasks.time, 'sleep'):
            with self.assertLogs('workflows.tasks', level='WARNING') as captured:
                workflow_tasks.process_workflow_execution(self.exec_log.id)

        marker = f'execution_log_id={self.exec_log.id}'
        errors = [r for r in captured.records if r.levelname == 'ERROR']
        self.assertTrue(errors, 'esperava logger.error na falha de envio')
        self.assertTrue(all(marker in r.getMessage() for r in captured.records))
        self.exec_log.refresh_from_db()
        self.assertEqual(self.exec_log.status, 'FAILED')

    def test_erro_interno_regista_execution_log_id(self):
        with mock.patch.object(
            workflow_tasks, '_dispatch_action_execution', side_effect=RuntimeError('x'),
        ):
            with self.assertLogs('workflows.tasks', level='ERROR') as captured:
                workflow_tasks.process_workflow_execution(self.exec_log.id)

        self.assertIn(f'execution_log_id={self.exec_log.id}', captured.output[0])
