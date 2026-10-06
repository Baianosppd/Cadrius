"""CAD-224: ação "Enviar e-mail" (EMAIL_SMTP) dos fluxos — antes dava "não implementado"."""
from django.core import mail
from django.test import TestCase, override_settings

from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from workflows.models import Workflow
from workflows.tasks import _send_workflow_email


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailActionTests(TestCase):
    def setUp(self):
        self.org = make_org()
        make_user('equipe@escritorio.com.br', self.org)
        self.wf = Workflow.objects.create(name='WF', organization=self.org)

    def test_envia_para_a_equipe(self):
        out = _send_workflow_email({'to': 'Equipe@escritorio.com.br', 'subject': 'Prazo', 'body': 'Vence amanhã'}, self.org, self.wf)
        self.assertEqual(out['recipient'], 'equipe')
        self.assertEqual(mail.outbox[0].to, ['equipe@escritorio.com.br'])

    def test_contato_so_com_consentimento(self):
        ana = Contact.objects.create(organization=self.org, name='Ana', email='ana@cliente.com', email_consent=False)
        with self.assertRaisesMessage(ValueError, 'autorização'):
            _send_workflow_email({'to': 'ana@cliente.com', 'body': 'Oi'}, self.org, self.wf)
        Contact.objects.filter(pk=ana.pk).update(email_consent=True)   # nome é cifrado: filtra por pk
        out = _send_workflow_email({'to': 'ana@cliente.com', 'body': 'Oi'}, self.org, self.wf)
        self.assertEqual(out['recipient'], 'contato')
        self.assertEqual(len(mail.outbox), 1)

    def test_recusa_desconhecido_e_invalido(self):
        with self.assertRaisesMessage(ValueError, 'LGPD'):
            _send_workflow_email({'to': 'qualquer@fora.com', 'body': 'Oi'}, self.org, self.wf)
        with self.assertRaisesMessage(ValueError, 'inválido'):
            _send_workflow_email({'to': 'nao-e-email', 'body': 'Oi'}, self.org, self.wf)
        self.assertEqual(mail.outbox, [])
