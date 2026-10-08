"""CAD-226: e-mail com visual do escritório e assinatura de quem envia."""
import base64
from unittest import mock

from django.core import mail
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from brain import profile
from cadrius.tests_security import make_org, make_user
from integrations import email_layout

PNG = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 64).decode()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailLayoutTests(APITestCase):
    def setUp(self):
        self.org = make_org('Andrade & Lima')
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def test_render_escapa_texto_e_usa_assinatura_da_pessoa_ou_do_escritorio(self):
        p = profile.get(self.org)
        p.signature = 'Andrade & Lima Advocacia\nOAB/SP 12.345'
        p.save()
        r = email_layout.render(self.org, 'Aviso', 'Olá <b>Maria</b>\n\nVeja https://exemplo.com/x?a=1', layout='classico')
        self.assertIn('&lt;b&gt;Maria&lt;/b&gt;', r['html'])
        self.assertIn('<a href="https://exemplo.com/x?a=1"', r['html'])
        self.assertIn('Georgia', r['html'])
        self.assertIn('OAB/SP 12.345', r['text'])
        self.owner.email_signature = 'Dra. Ana Andrade\nSócia'
        r = email_layout.render(self.org, 'Aviso', 'Oi', user=self.owner)
        self.assertIn('Dra. Ana Andrade', r['text'])
        self.assertNotIn('OAB/SP', r['text'])
        self.assertIn('#1d4ed8', r['html'])                                     # moderno com a cor padrão

    def test_envia_html_com_imagem_embutida(self):
        self.owner.email_signature, self.owner.email_signature_image = 'Dra. Ana', PNG
        self.owner.save()
        self.assertEqual(email_layout.send(self.org, 'Oi', 'Corpo', ['m@x.com'], user=self.owner, footer='Rodapé LGPD'), 'cadrius')
        msg = mail.outbox[0]
        self.assertIn('Rodapé LGPD', msg.body)
        html = msg.alternatives[0][0]
        self.assertIn('cid:assinatura-cadrius', html)
        self.assertEqual(msg.mixed_subtype, 'related')
        self.assertTrue(any(getattr(a, 'get', lambda *_: None)('Content-ID') == '<assinatura-cadrius>' for a in msg.attachments))

    def test_usa_smtp_do_escritorio_quando_houver(self):
        from django.core.mail import get_connection
        with mock.patch('integrations.services.office_sender', return_value=('contato@andrade.adv.br', get_connection())):
            self.assertEqual(email_layout.send(self.org, 'Oi', 'Corpo', ['m@x.com']), 'escritorio')
        self.assertEqual(mail.outbox[0].from_email, 'contato@andrade.adv.br')

    def test_api_assinatura_valida_imagem(self):
        res = self.c.put('/api/v1/integrations/email/assinatura/', {'texto': 'Dra. Ana', 'imagem': PNG}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email_signature, 'Dra. Ana')
        fake = 'data:image/png;base64,' + base64.b64encode(b'GIF89a').decode()
        self.assertEqual(self.c.put('/api/v1/integrations/email/assinatura/', {'imagem': fake}, format='json').status_code, 400)
        big = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG' + b'0' * 210_000).decode()
        self.assertEqual(self.c.put('/api/v1/integrations/email/assinatura/', {'imagem': big}, format='json').status_code, 400)
        self.assertEqual(self.c.put('/api/v1/integrations/email/assinatura/', {'imagem': 'javascript:x'}, format='json').status_code, 400)

    def test_api_visual_e_previa(self):
        res = self.c.put('/api/v1/integrations/email/visual/', {'visual': 'classico', 'cor': '#0f766e'}, format='json')
        self.assertEqual(res.json()['visual'], 'classico')
        self.assertEqual(self.c.put('/api/v1/integrations/email/visual/', {'visual': 'x', 'cor': 'red'}, format='json').status_code, 400)
        self.c.put('/api/v1/integrations/email/assinatura/', {'texto': 'Dra. Ana', 'imagem': PNG}, format='json')
        html = self.c.post('/api/v1/integrations/email/previa/', {}, format='json').json()['html']
        self.assertIn('#0f766e', html)
        self.assertIn('Dra. Ana', html)
        self.assertIn('data:image/png;base64,', html)
        other = APIClient()
        other.force_authenticate(self.member)
        self.assertEqual(other.put('/api/v1/integrations/email/visual/', {'visual': 'simples', 'cor': '#000000'}, format='json').status_code, 403)

    def test_regra_valida_visual(self):
        from automations import catalog
        rule = {'name': 'Boas-vindas', 'trigger': 'contact_created', 'conditions': [],
                'actions': [{'type': 'send_email', 'params': {'destinatario': 'contato', 'assunto': 'Oi', 'mensagem': 'Olá', 'visual': 'classico'}}]}
        self.assertEqual(catalog.clean_rule(rule)['actions'][0]['params']['visual'], 'classico')
        rule['actions'][0]['params']['visual'] = 'neon'
        with self.assertRaises(catalog.RuleError):
            catalog.clean_rule(rule)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailLogoTests(APITestCase):
    """CAD-231: logo da empresa no topo dos e-mails (todos os visuais), embutida como imagem CID."""

    def setUp(self):
        self.org = make_org('Andrade & Lima')
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def test_logo_salva_aparece_na_previa_e_vai_embutida(self):
        res = self.c.put('/api/v1/integrations/email/visual/', {'logo': PNG}, format='json')   # só a logo, sem mudar o visual
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['logo'], PNG)
        self.assertEqual(res.json()['visual'], 'moderno')
        html = self.c.post('/api/v1/integrations/email/previa/', {}, format='json').json()['html']
        self.assertIn(PNG, html)
        for layout in ('moderno', 'classico', 'simples'):
            self.assertIn('cid:logo-escritorio', email_layout.render(self.org, 'Oi', 'Corpo', layout=layout)['html'])
        email_layout.send(self.org, 'Oi', 'Corpo', ['m@x.com'])
        self.assertTrue(any(getattr(a, 'get', lambda *_: None)('Content-ID') == '<logo-escritorio>' for a in mail.outbox[0].attachments))
        fake = 'data:image/png;base64,' + base64.b64encode(b'GIF89a').decode()
        self.assertEqual(self.c.put('/api/v1/integrations/email/visual/', {'logo': fake}, format='json').status_code, 400)
        self.assertEqual(self.c.put('/api/v1/integrations/email/visual/', {'logo': ''}, format='json').json()['logo'], '')
        self.assertNotIn('logo-escritorio', email_layout.render(self.org, 'Oi', 'Corpo')['html'])
