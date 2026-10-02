from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from django_q.models import Schedule

from audit import service
from audit.models import AuditEvent
from audit.tests.test_audit import tamper


def run(name, *args):
    out = StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


class CommandsTests(TestCase):
    def test_verify_audit_chain_ok_e_adulterada(self):
        service.log('auth.logout')
        service.log('auth.logout')
        self.assertIn('Cadeia íntegra', run('verify_audit_chain'))
        self.assertTrue(AuditEvent.objects.filter(action='audit.chain_verified').exists())
        with tamper(), connection.cursor() as cur:
            cur.execute("UPDATE audit_auditevent SET reason='x' WHERE seq=(SELECT MIN(seq) FROM audit_auditevent)")
        with self.assertRaises(CommandError) as ctx:
            run('verify_audit_chain')
        self.assertIn('ADULTERADA', str(ctx.exception))
        self.assertTrue(AuditEvent.objects.filter(action='audit.chain_broken').exists())

    def test_run_anomaly_detection_e_purge_audit(self):
        self.assertIn('alerta', run('run_anomaly_detection'))
        old = timezone.now() - timedelta(days=500)
        with mock.patch('audit.service.timezone.now', return_value=old):
            service.log('auth.logout')
        self.assertIn('1 evento', run('purge_audit', '--days', '365'))

    def test_setup_security_schedules_e_idempotente(self):
        run('setup_security_schedules')
        total = Schedule.objects.count()
        self.assertGreaterEqual(total, 4)
        run('setup_security_schedules')
        self.assertEqual(Schedule.objects.count(), total)
        names = set(Schedule.objects.values_list('name', flat=True))
        self.assertIn('Privacidade: aplicar retenção (LGPD)', names)

    def test_enforce_retention_command(self):
        self.assertIn('Retenção aplicada', run('enforce_retention'))
