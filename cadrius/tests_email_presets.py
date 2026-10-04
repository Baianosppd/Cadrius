from django.test import SimpleTestCase

from cadrius.email_presets import PRESETS, resolve


class EmailPresetTests(SimpleTestCase):
    def test_gmail_e_trocas_futuras(self):
        self.assertEqual(resolve('GMAIL'), {'host': 'smtp.gmail.com', 'port': 587, 'tls': True})
        for name in ('brevo', 'ses', 'locaweb'):
            self.assertTrue(resolve(name)['host'])
        self.assertEqual(resolve('custom')['host'], '')

    def test_vazio_desliga_e_desconhecido_falha_cedo(self):
        self.assertEqual(resolve('')['host'], '')
        with self.assertRaises(ValueError):
            resolve('mailgun')
        self.assertIn('gmail', PRESETS)
