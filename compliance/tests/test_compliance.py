from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from aigov.guard import global_ai_enabled
from audit import service
from audit.models import AnomalyAlert, AuditEvent
from cadrius.tests_security import make_org, make_user
from compliance import checks, engine
from compliance.catalog import CATALOG
from compliance.models import ControlAssessment
from privacy.models import DataSubjectRequest

User = get_user_model()

PAGES = ['sc-overview', 'sc-events', 'sc-alerts', 'sc-posture', 'sc-ai', 'sc-privacy', 'sc-ropa']


def staff_user(email='sec@exemplo.com'):
    user = make_user(email)
    user.is_staff = True
    user.save()
    return user


class CatalogTests(TestCase):
    def test_catalogo_completo(self):
        self.assertEqual(len(CATALOG['iso27001']), 93)  # Anexo A completo
        self.assertEqual(len({c.id for c in CATALOG['iso27001']}), 93)
        self.assertGreaterEqual(len(CATALOG['iso27701']), 45)
        self.assertGreaterEqual(len(CATALOG['lgpd']), 25)
        themes = {c.theme for c in CATALOG['iso27001']}
        self.assertEqual(len(themes), 4)

    def test_toda_verificacao_referenciada_existe(self):
        used = {n for controls in CATALOG.values() for c in controls for n in c.checks}
        self.assertEqual(used - set(checks.CHECKS), set())


class ChecksTests(TestCase):
    def test_todas_as_verificacoes_executam_sem_erro(self):
        results = checks.run_all()
        self.assertEqual(set(results), set(checks.CHECKS))
        for name, result in results.items():
            self.assertIn(result.status, {'pass', 'partial', 'fail', 'unknown'}, name)
            self.assertNotIn('Erro ao verificar', result.detail, name)

    def test_verificacoes_refletem_o_estado_real(self):
        service.log('auth.logout')
        self.assertEqual(checks.run_all()['audit_trail'].status, 'pass')
        self.assertEqual(checks.run_all()['dsr_sla'].status, 'pass')
        self.assertEqual(checks.run_all()['mfa'].status, 'partial')  # TOTP ativo, mas donos/admins ainda opcional (CAD-169)
        # SLA de titular vencido derruba a verificação
        user = make_user('t@exemplo.com')
        from django.utils import timezone
        from datetime import timedelta
        DataSubjectRequest.objects.create(user=user, user_ref=str(user.pk), type='access',
                                          opened_at=timezone.now() - timedelta(days=20))
        self.assertEqual(checks.run_all()['dsr_sla'].status, 'fail')

    def test_adulteracao_da_trilha_e_detectada_pela_verificacao(self):
        from audit.tests.test_audit import tamper
        from django.db import connection
        for _ in range(3):
            service.log('auth.logout')
        with tamper(), connection.cursor() as cur:
            cur.execute("UPDATE audit_auditevent SET reason = 'x' WHERE seq = (SELECT MIN(seq) FROM audit_auditevent)")
        self.assertEqual(checks.run_all()['audit_trail'].status, 'fail')


class EngineTests(TestCase):
    def test_pontuacao_e_origem(self):
        rows = engine.evaluate('lgpd')
        summary = engine.score(rows)
        self.assertEqual(summary['total'], len(CATALOG['lgpd']))
        self.assertTrue(0 <= summary['score'] <= 100)
        by_id = {r.control.id: r for r in rows}
        self.assertIn(by_id['37'].status, {'implemented', 'partial'})   # RoPA existe
        self.assertEqual(by_id['6-IX'].source, 'manual')                 # sem verificação automática

    def test_avaliacao_manual_e_nao_aplicavel(self):
        ControlAssessment.objects.create(framework='iso27001', control_id='7.1', status='implemented', owner='Infra')
        ControlAssessment.objects.create(framework='iso27001', control_id='7.2', status='not_applicable', justification='SaaS sem sede física')
        ControlAssessment.objects.create(framework='iso27001', control_id='7.3', status='not_applicable')  # sem justificativa: ignorado
        rows = {r.control.id: r for r in engine.evaluate('iso27001')}
        self.assertEqual(rows['7.1'].status, 'implemented')
        self.assertEqual(rows['7.2'].status, 'not_applicable')
        self.assertEqual(rows['7.3'].status, 'not_assessed')
        self.assertEqual(engine.score(list(rows.values()))['counts']['not_applicable'], 1)

    def test_verificacao_automatica_prevalece_sobre_status_manual(self):
        ControlAssessment.objects.create(framework='iso27001', control_id='8.5', status='implemented')
        row = {r.control.id: r for r in engine.evaluate('iso27001')}['8.5']
        self.assertEqual(row.source, 'mixed')
        self.assertNotEqual(row.status, 'implemented')  # MFA ausente mantém "parcial"


class ScreensTests(TestCase):
    def setUp(self):
        self.staff = staff_user()
        self.client.force_login(self.staff)

    def test_todas_as_telas_renderizam(self):
        service.log('auth.login.failure', outcome='denied', actor_type='anonymous')
        AnomalyAlert.objects.create(rule='A5_ENUMERATION', severity='critical', summary='teste', dedupe_key='k1')
        for name in PAGES:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)
            self.assertContains(resp, 'Centro de Segurança')
        for fw in CATALOG:
            self.assertEqual(self.client.get(reverse('sc-framework', kwargs={'framework': fw})).status_code, 200, fw)
        self.assertEqual(self.client.get('/security-center/inexistente/').status_code, 404)

    def test_acesso_restrito_a_staff_e_negado_fica_auditado(self):
        self.client.logout()
        resp = self.client.get(reverse('sc-overview'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp.url)
        common = make_user('comum@exemplo.com')
        self.client.force_login(common)
        self.assertEqual(self.client.get(reverse('sc-overview')).status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action='permission.denied', reason__contains='security-center').exists())

    def test_acesso_ao_centro_e_auditado(self):
        self.client.get(reverse('sc-posture'))
        self.assertTrue(AuditEvent.objects.filter(action='audit.viewed', reason__contains='/security-center/posture/').exists())

    def test_filtros_da_trilha(self):
        service.log('auth.login.failure', outcome='denied', actor_type='anonymous', actor_label='x***@a.com')
        service.log('workflow.created')
        resp = self.client.get(reverse('sc-events'), {'prefix': 'auth', 'outcome': 'denied'})
        self.assertContains(resp, 'auth.login.failure')
        self.assertNotContains(resp, 'workflow.created')

    def test_avaliar_controle_manual_e_exigir_justificativa(self):
        url = reverse('sc-assess')
        base = {'framework': 'iso27001', 'control_id': '7.1', 'owner': 'Infra', 'evidence_url': 'https://x.y/doc'}
        bad = self.client.post(url, {**base, 'status': 'not_applicable'}, follow=True)
        self.assertContains(bad, 'exige justificativa')
        self.assertFalse(ControlAssessment.objects.exists())
        ok = self.client.post(url, {**base, 'status': 'implemented'}, follow=True)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ControlAssessment.objects.get().owner, 'Infra')
        self.assertTrue(AuditEvent.objects.filter(action='compliance.assessment_updated').exists())
        self.assertEqual(self.client.post(url, {'framework': 'x', 'control_id': 'y', 'status': 'z'}).status_code, 302)

    def test_exportacao_csv_a_prova_de_injecao(self):
        ControlAssessment.objects.create(framework='lgpd', control_id='6-IX', status='implemented', owner='=cmd|calc')
        resp = self.client.get(reverse('sc-framework-csv', kwargs={'framework': 'lgpd'}))
        body = resp.content.decode()
        self.assertIn("'=cmd|calc", body)
        self.assertIn('6-IX', body)
        self.assertEqual(self.client.get(reverse('sc-ropa'), {'format': 'csv'}).status_code, 200)

    def test_triagem_de_alerta_e_verificacao_da_cadeia(self):
        alert = AnomalyAlert.objects.create(rule='A3', severity='high', summary='s', dedupe_key='k2')
        self.client.post(reverse('sc-alert-review', kwargs={'pk': alert.pk}), {'status': 'false_positive'})
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'false_positive')
        self.assertTrue(AuditEvent.objects.filter(action='anomaly.reviewed').exists())
        resp = self.client.post(reverse('sc-verify-chain'), follow=True)
        self.assertContains(resp, 'Cadeia íntegra')

    def test_kill_switch_pela_tela_exige_motivo(self):
        url = reverse('sc-ai-switch')
        self.client.post(url, {'enabled': '0'})
        self.assertTrue(global_ai_enabled())
        self.client.post(url, {'enabled': '0', 'reason': 'incidente com provedor'})
        from django.core.cache import cache
        cache.clear()
        self.assertFalse(global_ai_enabled())
        self.client.post(url, {'enabled': '1'})
        cache.clear()
        self.assertTrue(global_ai_enabled())

    def test_post_sem_csrf_e_recusado(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.staff)
        self.assertEqual(strict.post(reverse('sc-ai-switch'), {'enabled': '0', 'reason': 'x'}).status_code, 403)


class SecurityApiTests(TestCase):
    def test_api_somente_staff(self):
        org = make_org()
        owner = make_user('o@exemplo.com', org, role='OWNER')
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(owner)
        for path in ('overview', 'controls', 'checks', 'ropa'):
            self.assertEqual(client.get(f'/api/v1/security/{path}/').status_code, 403, path)
        client.force_authenticate(staff_user('s@exemplo.com'))
        self.assertEqual(client.get('/api/v1/security/overview/').json()['code'], 'mfa_required')   # sem MFA não entra (CAD-169)
        client.force_authenticate(staff_user('s2@exemplo.com'), token={'amr': 'mfa'})
        self.assertEqual(client.get('/api/v1/security/overview/').status_code, 200)
        data = client.get('/api/v1/security/controls/?framework=iso27001').data
        self.assertEqual(data['total'], 93)
        self.assertEqual(client.get('/api/v1/security/controls/?framework=x').status_code, 400)
        self.assertTrue(client.get('/api/v1/security/checks/').data)
        self.assertTrue(client.get('/api/v1/security/ropa/').data)

    def test_snapshot_command(self):
        from django.core.management import call_command
        from compliance.models import ComplianceSnapshot
        call_command('snapshot_compliance', verbosity=0)
        self.assertEqual(ComplianceSnapshot.objects.count(), 3)
