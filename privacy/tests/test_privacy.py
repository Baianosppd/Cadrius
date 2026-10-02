from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import legal_acceptance, make_org, make_user
from emails.models import EmailMessage, MailBox
from integrations.models import AppConnection
from privacy import consent, dsr
from privacy.models import (
    ConsentRecord, DataSubjectRequest, LegalDocument, OrganizationOffboarding, SubprocessorEntry,
)
from privacy.retention import enforce_retention
from workflows.models import ExecutionLog, Workflow


def accept_all(user):
    for doc in consent.current_documents(consent.REQUIRED_KINDS):
        consent.record_consent(user, doc)


class LegalDocumentTests(TestCase):
    def test_seed_publica_documentos_e_suboperadores(self):
        kinds = set(LegalDocument.objects.filter(is_current=True).values_list('kind', flat=True))
        self.assertTrue({'terms', 'privacy', 'ciencia', 'ai_notice'} <= kinds)
        self.assertTrue(LegalDocument.objects.filter(needs_legal_review=False).count() == 0)
        self.assertTrue(SubprocessorEntry.objects.filter(name='OpenAI').exists())

    def test_texto_publicado_e_imutavel_e_hash_confere(self):
        doc = LegalDocument.objects.get(kind='terms', is_current=True)
        import hashlib
        self.assertEqual(doc.content_sha256, hashlib.sha256(doc.content_md.encode()).hexdigest())
        doc.content_md += ' alterado'
        with self.assertRaises(ValueError):
            doc.save()

    def test_nova_versao_substitui_a_vigente(self):
        new = LegalDocument.objects.create(kind='terms', version='2.0', title='T', content_md='novo', is_current=True)
        self.assertEqual(LegalDocument.objects.filter(kind='terms', is_current=True).get(), new)


class ConsentTests(APITestCase):
    def test_cadastro_exige_aceite_da_versao_vigente_e_grava_prova(self):
        base = {'email': 'c@example.com', 'password': 'Str0ng-Passw0rd!x'}
        resp = self.client.post('/api/v1/auth/register/', base)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('accepted_terms_version', resp.data)

        wrong = {**base, **{k: '0.0' for k in legal_acceptance()}}
        self.assertEqual(self.client.post('/api/v1/auth/register/', wrong).status_code, 400)

        ok = self.client.post('/api/v1/auth/register/', {**base, **legal_acceptance()})
        self.assertEqual(ok.status_code, 201, ok.data)
        records = ConsentRecord.objects.filter(user_ref=str(ok.data['id']))
        self.assertEqual(records.count(), 3)
        doc = LegalDocument.objects.get(kind='ciencia', is_current=True)
        self.assertEqual(records.get(document=doc).evidence_sha256, doc.content_sha256)
        self.assertTrue(AuditEvent.objects.filter(action='consent.granted').exists())

    def test_consentimento_e_append_only(self):
        user = make_user('a@example.com')
        accept_all(user)
        rec = ConsentRecord.objects.first()
        with self.assertRaises(ValueError):
            rec.save()
        with self.assertRaises(ValueError):
            rec.delete()

    def test_api_bloqueia_com_428_ate_aceitar_e_libera_depois(self):
        user = make_user('p@example.com', make_org(), role='OWNER')
        tokens = self.client.post('/api/v1/auth/token/', {'username': user.email, 'password': 'Str0ng-Passw0rd!x'}).data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        cache.clear()

        blocked = self.client.get('/api/v1/tasks/')
        self.assertEqual(blocked.status_code, 428)
        self.assertEqual(blocked.data['code'], 'consent_required')
        self.assertEqual(len(blocked.data['pending']), 3)
        # rotas de consentimento/perfil seguem acessíveis
        self.assertEqual(self.client.get('/api/v1/legal/consents/me/').status_code, 200)
        self.assertEqual(self.client.get('/api/v1/auth/user/').status_code, 200)

        for item in blocked.data['pending']:
            resp = self.client.post('/api/v1/legal/consents/', {'document_id': item['id'], 'granted': True})
            self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(self.client.get('/api/v1/tasks/').status_code, 200)

    def test_nova_versao_exige_reaceite(self):
        user = make_user('r@example.com')
        accept_all(user)
        cache.clear()
        self.assertFalse(consent.has_pending(user))
        LegalDocument.objects.create(kind='privacy', version='2.0', title='P2', content_md='x', is_current=True)
        cache.clear()
        self.assertEqual([d.kind for d in consent.pending_documents(user)], ['privacy'])

    def test_documento_essencial_nao_e_revogavel_isoladamente(self):
        user = make_user('e@example.com')
        accept_all(user)
        self.client.force_authenticate(user)
        doc = LegalDocument.objects.get(kind='terms', is_current=True)
        resp = self.client.post('/api/v1/legal/consents/', {'document_id': doc.pk, 'granted': False})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'essential_document')

    def test_documentos_e_suboperadores_sao_publicos(self):
        self.assertEqual(self.client.get('/api/v1/legal/documents/').status_code, 200)
        resp = self.client.get('/api/v1/legal/subprocessors/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any(s['name'] == 'OpenAI' for s in resp.data))

    @override_settings(LEGAL_ACCEPTANCE_REQUIRED=False)
    def test_aceite_pode_ser_desligado_por_configuracao(self):
        self.assertEqual(consent.pending_documents(make_user('d@example.com')), [])


class DataSubjectTests(APITestCase):
    def setUp(self):
        self.org = make_org()
        self.user = make_user('t@example.com', self.org, role='OWNER')
        accept_all(self.user)
        self.client.force_authenticate(self.user)

    def test_pedido_do_titular_tem_prazo_de_15_dias(self):
        resp = self.client.post('/api/v1/privacy/requests/', {'type': 'access', 'notes': 'quero meus dados'})
        self.assertEqual(resp.status_code, 201, resp.data)
        req = DataSubjectRequest.objects.get()
        self.assertEqual((req.due_at - req.opened_at).days, 15)
        self.assertFalse(req.overdue)
        self.assertTrue(AuditEvent.objects.filter(action='dsr.opened').exists())

    def test_exportacao_traz_so_dados_do_proprio_titular(self):
        other = make_user('o@example.com', make_org('B'), role='OWNER')
        MailBox.objects.create(user=other, name='alheia', imap_host='h', username='u', password='p')
        MailBox.objects.create(user=self.user, name='minha', imap_host='h', username='u', password='p')
        data = self.client.get('/api/v1/privacy/me/export/').data
        self.assertEqual(data['profile']['email'], 't@example.com')
        self.assertEqual([m['name'] for m in data['mailboxes']], ['minha'])
        self.assertNotIn('password', str(data['mailboxes']))
        self.assertTrue(AuditEvent.objects.filter(action='data.export').exists())

    def test_eliminacao_anonimiza_e_preserva_trilha_e_consentimentos(self):
        box = MailBox.objects.create(user=self.user, name='m', imap_host='h', username='u', password='p')
        EmailMessage.objects.create(mailbox=box, message_id='<1>', subject='s', sender='x@y.com',
                                    received_at=timezone.now(), body_text='conteudo')
        AppConnection.objects.create(user=self.user, name='c', app_name='WEBHOOK', credentials={'k': 'v'})
        self.user.cpf = '123.456.789-09'
        self.user.save()
        req = dsr.open_request(self.user, 'deletion')
        dsr.fulfill_request(req, handler_id='staff1', resolution='ok')

        self.user.refresh_from_db()
        self.assertEqual(self.user.cpf, None)
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.email.endswith('@anonimizado.invalid'))
        self.assertFalse(self.user.has_usable_password())
        self.assertEqual(MailBox.objects.filter(user=self.user).count(), 0)
        self.assertEqual(EmailMessage.objects.count(), 0)
        self.assertEqual(AppConnection.objects.filter(user=self.user).count(), 0)
        self.assertFalse(self.user.memberships.filter(is_active=True).exists())
        # prova de consentimento e trilha de segurança permanecem
        self.assertTrue(ConsentRecord.objects.filter(user_ref=str(self.user.pk)).exists())
        self.assertTrue(AuditEvent.objects.filter(action='anonymization.run').exists())
        req.refresh_from_db()
        self.assertEqual(req.status, 'fulfilled')


class OffboardingTests(APITestCase):
    def setUp(self):
        self.org = make_org('Escritório Alfa')
        self.owner = make_user('own@example.com', self.org, role='OWNER')
        accept_all(self.owner)
        self.client.force_authenticate(self.owner)

    def test_somente_owner_e_com_confirmacao(self):
        member = make_user('m@example.com', self.org, role='ADMIN')
        accept_all(member)
        self.client.force_authenticate(member)
        self.assertEqual(self.client.post('/api/v1/privacy/organization/close/', {'confirm': 'Escritório Alfa'}).status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post('/api/v1/privacy/organization/close/', {'confirm': 'errado'}).status_code, 400)

    def test_encerramento_mantem_30_dias_e_depois_elimina(self):
        Workflow.objects.create(name='w', organization=self.org)
        box = MailBox.objects.create(user=self.owner, name='m', imap_host='h', username='u', password='p')
        resp = self.client.post('/api/v1/privacy/organization/close/', {'confirm': 'Escritório Alfa'})
        self.assertEqual(resp.status_code, 202, resp.data)
        self.org.refresh_from_db()
        self.assertFalse(self.org.is_active)
        off = OrganizationOffboarding.objects.get()
        self.assertGreaterEqual((off.purge_after - timezone.now()).days, 29)

        # antes do prazo: nada é eliminado
        enforce_retention()
        self.assertTrue(type(self.org).objects.filter(pk=self.org.pk).exists())
        # depois do prazo: elimina escritório e os recursos exclusivos dele
        OrganizationOffboarding.objects.update(purge_after=timezone.now() - timedelta(days=1))
        result = enforce_retention()
        self.assertEqual(result['organizations_purged'], 1)
        self.assertFalse(type(self.org).objects.filter(pk=self.org.pk).exists())
        self.assertFalse(MailBox.objects.filter(pk=box.pk).exists())
        self.assertEqual(OrganizationOffboarding.objects.get().status, 'purged')


class RetentionTests(TestCase):
    def test_expurga_conteudo_vencido_e_preserva_metricas(self):
        org = make_org()
        user = make_user('r@example.com', org)
        box = MailBox.objects.create(user=user, name='m', imap_host='h', username='u', password='p')
        old, recent = timezone.now() - timedelta(days=120), timezone.now()
        mails = []
        for i, (created, dispatched) in enumerate([(old, True), (old, False), (recent, True)]):
            mail = EmailMessage.objects.create(mailbox=box, message_id=f'<{i}>', subject='s', sender='x@y.com',
                                               received_at=created, body_text='CORPO', is_dispatched=dispatched)
            EmailMessage.objects.filter(pk=mail.pk).update(created_at=created)
            mails.append(mail.pk)
        wf = Workflow.objects.create(name='w', organization=org)
        log_old = ExecutionLog.objects.create(workflow=wf, status='SUCCESS', trigger_payload={'cpf': '1'},
                                              final_result={'x': 1}, execution_time_ms=1500)
        ExecutionLog.objects.filter(pk=log_old.pk).update(created_at=old)

        result = enforce_retention()
        bodies = dict(EmailMessage.objects.values_list('pk', 'body_text'))
        self.assertEqual(bodies[mails[0]], '')          # vencido e já despachado -> expurgado
        self.assertEqual(bodies[mails[1]], 'CORPO')     # vencido mas NÃO processado -> preservado
        self.assertEqual(bodies[mails[2]], 'CORPO')     # recente -> preservado
        log_old.refresh_from_db()
        self.assertIsNone(log_old.trigger_payload)
        self.assertEqual(log_old.execution_time_ms, 1500)  # métrica de ROI preservada
        self.assertEqual(result['email_bodies'], 1)
        self.assertTrue(AuditEvent.objects.filter(action='retention.purged').exists())
