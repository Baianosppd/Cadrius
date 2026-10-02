from datetime import timedelta
from unittest import mock

from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

import unittest
from contextlib import contextmanager

from audit import detectors, service
from audit.models import AnomalyAlert, AuditCheckpoint, AuditEvent, ImmutableError
from audit.redaction import mask_email, redact
from audit.retention import purge_old_events
from audit.verify import verify_chain
from cadrius.tests_security import make_org, make_user
from emails.models import EmailMessage, MailBox


@contextmanager
def tamper():
    """
    Simula um atacante com acesso ao banco. Em PostgreSQL o trigger de imutabilidade bloqueia o
    UPDATE/DELETE; aqui ele é desativado SÓ para provar que a cadeia de hash detecta a adulteração.
    """
    if connection.vendor == 'postgresql':
        with connection.cursor() as cur:
            cur.execute('ALTER TABLE audit_auditevent DISABLE TRIGGER audit_auditevent_immutable')
    try:
        yield
    finally:
        if connection.vendor == 'postgresql':
            with connection.cursor() as cur:
                cur.execute('ALTER TABLE audit_auditevent ENABLE TRIGGER audit_auditevent_immutable')


class RedactionTests(TestCase):
    def test_nao_regista_pii_nem_segredos(self):
        data = redact({
            'password': 'x', 'token': 'abc', 'cpf': '123.456.789-09', 'body_text': 'corpo do e-mail',
            'fields': ['a', 'b'], 'nota': 'contato joao@exemplo.com cpf 123.456.789-09 jwt eyJabc.def.ghi',
        })
        flat = str(data)
        self.assertNotIn('joao@exemplo.com', flat)
        self.assertNotIn('123.456.789-09', flat)
        self.assertNotIn('eyJabc', flat)
        self.assertEqual(data['password'], '<redacted>')
        self.assertEqual(data['body_text'], '<redacted>')
        self.assertEqual(data['fields'], ['a', 'b'])
        self.assertEqual(mask_email('joao@exemplo.com'), 'j***@exemplo.com')


class ChainTests(TestCase):
    def test_cadeia_integra_e_detecta_adulteracao(self):
        for i in range(5):
            self.assertIsNotNone(service.log('auth.logout', reason=f'r{i}'))
        self.assertEqual(AuditEvent.objects.count(), 5)
        self.assertTrue(verify_chain()['ok'])

        # Adulteração "por fora" (SQL direto, como faria um atacante com acesso ao banco).
        target = AuditEvent.objects.order_by('seq')[2]
        with tamper(), connection.cursor() as cur:
            cur.execute('UPDATE audit_auditevent SET reason = %s WHERE seq = %s', ['adulterado', target.seq])
        result = verify_chain()
        self.assertFalse(result['ok'])
        self.assertEqual(result['first_bad_seq'], target.seq)

    def test_remocao_de_evento_quebra_a_cadeia(self):
        for _ in range(4):
            service.log('auth.logout')
        victim = AuditEvent.objects.order_by('seq')[1]
        with tamper(), connection.cursor() as cur:
            cur.execute('DELETE FROM audit_auditevent WHERE seq = %s', [victim.seq])
        self.assertFalse(verify_chain()['ok'])

    @unittest.skipUnless(connection.vendor == 'postgresql', 'trigger de imutabilidade é específico do PostgreSQL')
    def test_trigger_do_postgres_bloqueia_update_delete_e_truncate(self):
        from django.db import InternalError, transaction
        event = service.log('auth.logout')
        for sql, params in (
            ('UPDATE audit_auditevent SET reason = %s WHERE seq = %s', ['x', event.seq]),
            ('DELETE FROM audit_auditevent WHERE seq = %s', [event.seq]),
            ('TRUNCATE audit_auditevent', []),
        ):
            with self.subTest(sql=sql.split()[0]), self.assertRaises(InternalError), transaction.atomic(), \
                    connection.cursor() as cur:
                cur.execute(sql, params)
        self.assertTrue(verify_chain()['ok'])

    def test_api_do_modelo_e_append_only(self):
        event = service.log('auth.logout')
        event.reason = 'x'
        with self.assertRaises(ImmutableError):
            event.save()
        with self.assertRaises(ImmutableError):
            event.delete()
        with self.assertRaises(ImmutableError):
            AuditEvent.objects.all().update(reason='x')
        with self.assertRaises(ImmutableError):
            AuditEvent.objects.all().delete()

    def test_falha_de_auditoria_nao_propaga(self):
        with mock.patch('audit.service.AuditChainHead.objects') as heads:
            heads.select_for_update.side_effect = RuntimeError('db down')
            self.assertIsNone(service.log('auth.logout'))  # não levanta
        self.assertIsNone(service.log('acao.inexistente'))

    def test_retencao_preserva_verificabilidade(self):
        old = timezone.now() - timedelta(days=400)
        with mock.patch('audit.service.timezone.now', return_value=old):  # eventos "antigos" válidos na cadeia
            service.log('auth.logout')
            service.log('auth.logout')
        for _ in range(3):
            service.log('auth.logout')
        self.assertTrue(verify_chain()['ok'])

        self.assertEqual(purge_old_events(days=365), 2)
        self.assertEqual(AuditCheckpoint.objects.count(), 1)
        self.assertTrue(verify_chain()['ok'])  # recomeça no checkpoint
        self.assertEqual(AuditEvent.objects.filter(action='retention.purged').count(), 1)


class AuthEventsTests(APITestCase):
    def test_login_sucesso_falha_e_logout_geram_eventos_com_request_id(self):
        make_user('a@exemplo.com')
        bad = self.client.post('/api/v1/auth/token/', {'username': 'a@exemplo.com', 'password': 'errada'})
        self.assertEqual(bad.status_code, 401)
        good = self.client.post('/api/v1/auth/token/', {'username': 'a@exemplo.com', 'password': 'Str0ng-Passw0rd!x'})
        self.assertEqual(good.status_code, 200)
        self.assertIn('X-Request-ID', good.headers)

        actions = list(AuditEvent.objects.values_list('action', flat=True))
        self.assertIn('auth.login.failure', actions)
        self.assertIn('auth.login.success', actions)
        ok = AuditEvent.objects.get(action='auth.login.success')
        self.assertEqual(ok.request_id, good.headers['X-Request-ID'])
        self.assertEqual(ok.actor_label, 'a***@exemplo.com')
        self.assertNotIn('a@exemplo.com', str(list(AuditEvent.objects.values())))  # e-mail nunca em claro

    def test_403_e_registado_como_permission_denied(self):
        org = make_org()
        viewer = make_user('v@exemplo.com', org, role='MEMBER')
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get('/api/v1/audit/events/').status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action='permission.denied').exists())


class ViewSetAuditTests(APITestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('o@exemplo.com', self.org, role='OWNER')
        self.client.force_authenticate(self.owner)

    def test_crud_de_mailbox_e_leitura_de_email_ficam_na_trilha(self):
        resp = self.client.post('/api/v1/mailboxes/', {
            'name': 'cx', 'imap_host': 'imap.exemplo.com', 'imap_port': 993, 'username': 'u'})
        self.assertEqual(resp.status_code, 201, resp.data)
        box = MailBox.objects.get(pk=resp.data['id'])
        mail = EmailMessage.objects.create(mailbox=box, message_id='<1>', subject='s', sender='x@y.com',
                                           received_at=timezone.now(), body_text='SEGREDO-DO-CORPO')
        self.assertEqual(self.client.get(f'/api/v1/emails/{mail.pk}/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/emails/').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/v1/mailboxes/{box.pk}/').status_code, 204)

        actions = set(AuditEvent.objects.values_list('action', flat=True))
        self.assertTrue({'mailbox.created', 'data.read', 'data.bulk_read', 'mailbox.deleted'} <= actions)
        self.assertNotIn('SEGREDO-DO-CORPO', str(list(AuditEvent.objects.values())))

    def test_convite_com_cargo_admin_e_auditado(self):
        resp = self.client.post('/api/v1/teams/members/', {'email': 'n@exemplo.com', 'role': 'ADMIN'})
        self.assertEqual(resp.status_code, 201, resp.data)
        ev = AuditEvent.objects.get(action='member.invited')
        self.assertEqual(ev.changes['role'], 'ADMIN')
        self.assertEqual(str(ev.organization_id), str(self.org.pk))


class OrgAuditApiTests(APITestCase):
    def setUp(self):
        self.org_a, self.org_b = make_org('A'), make_org('B')
        self.owner_a = make_user('a@a.com', self.org_a, role='OWNER')
        self.owner_b = make_user('b@b.com', self.org_b, role='OWNER')
        service.log('workflow.created', actor=self.owner_a, organization=self.org_a, target_type='Workflow', target_id='1')
        service.log('workflow.created', actor=self.owner_b, organization=self.org_b, target_type='Workflow', target_id='2')

    def test_cada_escritorio_so_ve_a_sua_trilha(self):
        self.client.force_authenticate(self.owner_a)
        resp = self.client.get('/api/v1/audit/events/?action=workflow.created')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([e['target_id'] for e in resp.data['results']], ['1'])

    def test_export_csv_e_auditado_e_seguro_contra_injecao(self):
        service.log('audit.viewed', actor=self.owner_a, organization=self.org_a, reason='=HYPERLINK("x")')
        self.client.force_authenticate(self.owner_a)
        resp = self.client.get('/api/v1/audit/events/export/')
        self.assertEqual(resp.status_code, 200)
        body = b''.join(resp.streaming_content).decode()
        self.assertIn("'=HYPERLINK", body)
        self.assertTrue(AuditEvent.objects.filter(action='audit.export').exists())

    def test_summary(self):
        self.client.force_authenticate(self.owner_a)
        resp = self.client.get('/api/v1/audit/summary/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('total_events', resp.data)


class AdminAuditTests(TestCase):
    def test_log_entry_do_admin_vira_evento(self):
        staff = make_user('s@exemplo.com')
        staff.is_staff = True
        staff.save()
        LogEntry.objects.create(user=staff, content_type=ContentType.objects.get_for_model(MailBox),
                                object_id='7', object_repr='cx', action_flag=ADDITION, change_message='[]')
        ev = AuditEvent.objects.get(action='admin.add')
        self.assertEqual(ev.target_id, '7')
        self.assertEqual(ev.actor_type, 'admin')


def _raw_update(seq, **fields):
    """Altera um evento por SQL direto — só em testes, para simular histórico/IPs."""
    sets = ', '.join(f'{k} = %s' for k in fields)
    with tamper(), connection.cursor() as cur:
        cur.execute(f'UPDATE audit_auditevent SET {sets} WHERE seq = %s', [*fields.values(), seq])


class DetectorTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

    def test_falhas_seguidas_de_sucesso_no_mesmo_ip(self):
        user = make_user('u@exemplo.com')
        for _ in range(3):
            _raw_update(service.log('auth.login.failure', outcome='denied', actor_type='anonymous').seq, ip='203.0.113.9')
        _raw_update(service.log('auth.login.success', actor=user).seq, ip='203.0.113.9')
        detectors.run_detectors(self.now)
        alert = AnomalyAlert.objects.get(rule='A6_FAILS_THEN_SUCCESS')
        self.assertEqual(alert.ip, '203.0.113.9')
        self.assertEqual(alert.severity, 'high')

    def test_pico_de_leitura_e_enumeracao(self):
        user = make_user('r@exemplo.com')
        for _ in range(100):
            service.log('data.read', actor=user)
        for _ in range(10):
            service.log('permission.denied', actor=user, outcome='denied')
        detectors.run_detectors(self.now)
        rules = set(AnomalyAlert.objects.values_list('rule', flat=True))
        self.assertTrue({'A3_READ_BURST', 'A5_ENUMERATION'} <= rules)
        n = AnomalyAlert.objects.count()
        detectors.run_detectors(self.now)  # idempotente na mesma janela
        self.assertEqual(AnomalyAlert.objects.count(), n)
        self.assertTrue(AuditEvent.objects.filter(action='anomaly.detected').exists())

    def test_escalada_de_privilegio(self):
        user = make_user('p@exemplo.com')
        service.log('member.invited', actor=user, changes={'role': 'OWNER'})
        detectors.run_detectors(self.now)
        self.assertTrue(AnomalyAlert.objects.filter(rule='A7_PRIVILEGE_CHANGE').exists())

    def test_varios_ips_em_15_min(self):
        user = make_user('m@exemplo.com')
        for ip in ('198.51.100.1', '198.51.100.2', '198.51.100.3'):
            _raw_update(service.log('data.read', actor=user).seq, ip=ip)
        detectors.run_detectors(self.now)
        self.assertTrue(AnomalyAlert.objects.filter(rule='A10_MULTI_IP').exists())

    def test_baseline_individual_hora_incomum_e_ip_novo(self):
        user = make_user('h@exemplo.com')
        tz = timezone.get_current_timezone()
        usual_hour = (timezone.localtime(self.now, tz).hour + 12) % 24  # nunca coincide com a hora atual
        base = timezone.localtime(self.now, tz).replace(hour=usual_hour, minute=0, second=0)
        for i in range(60):  # histórico: sempre nessa hora, sempre do mesmo IP
            _raw_update(service.log('data.read', actor=user).seq,
                        occurred_at=base - timedelta(days=1 + i % 20), ip='192.0.2.10')
        _raw_update(service.log('data.read', actor=user).seq, ip='192.0.2.99')  # agora, outro IP
        detectors.run_detectors(self.now)
        rules = set(AnomalyAlert.objects.values_list('rule', flat=True))
        self.assertTrue({'A2_OFF_HOURS', 'A1_NEW_IP'} <= rules)

    def test_sem_historico_suficiente_nao_ha_baseline(self):
        user = make_user('n@exemplo.com')
        service.log('data.read', actor=user)
        detectors.run_detectors(self.now)
        self.assertFalse(AnomalyAlert.objects.filter(rule__in=['A1_NEW_IP', 'A2_OFF_HOURS']).exists())
