import re
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from audit.models import AuditEvent

User = get_user_model()
OLD, NEW = 'Str0ng-Passw0rd!x', 'N0va-Senha-Segura#42'


def link_params(message):
    fragment = re.search(r'#(uid=[^\s]+)', message.body).group(1)
    return {k: v[0] for k, v in parse_qs(fragment).items()}


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', FRONTEND_URL='https://app.example.com')
class PasswordResetTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('ana@example.com', 'ana@example.com', OLD, first_name='Ana')

    def request_reset(self, email='ana@example.com'):
        return self.client.post('/api/v1/auth/password-reset/', {'email': email}, format='json')

    def test_pedido_envia_email_com_token_no_fragmento(self):
        resp = self.request_reset()
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['ana@example.com'])
        self.assertIn('https://app.example.com/redefinir-senha#uid=', msg.body)
        self.assertNotIn('?token', msg.body)  # nunca na query (vazaria por Referer/logs)
        self.assertTrue(AuditEvent.objects.filter(action='auth.password.reset_requested', outcome='success').exists())

    def test_resposta_identica_para_email_inexistente_e_nada_enviado(self):
        a = self.request_reset('fantasma@example.com')
        b = self.request_reset()
        self.assertEqual((a.status_code, a.data), (b.status_code, b.data))
        self.assertEqual(len(mail.outbox), 1)  # só o existente

    def test_limite_por_email(self):
        for _ in range(5):
            self.assertEqual(self.request_reset().status_code, 202)
        self.assertEqual(len(mail.outbox), 3)  # PER_EMAIL_LIMIT; o resto é ignorado em silêncio

    def test_confirmacao_troca_senha_e_token_e_de_uso_unico(self):
        self.request_reset()
        params = link_params(mail.outbox[0])
        resp = self.client.post('/api/v1/auth/password-reset/confirm/', {**params, 'new_password': NEW}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        again = self.client.post('/api/v1/auth/password-reset/confirm/', {**params, 'new_password': 'Outra-Senha#999x'},
                                 format='json')
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.data['code'], 'invalid_token')
        self.assertTrue(AuditEvent.objects.filter(action='auth.password.reset', outcome='success').exists())

    def test_confirmacao_encerra_sessoes_antigas(self):
        refresh = RefreshToken.for_user(self.user)
        self.request_reset()
        params = link_params(mail.outbox[0])
        self.client.post('/api/v1/auth/password-reset/confirm/', {**params, 'new_password': NEW}, format='json')
        self.assertTrue(BlacklistedToken.objects.filter(token__jti=refresh['jti']).exists())
        resp = self.client.post('/api/v1/auth/token/refresh/', {'refresh': str(refresh)}, format='json')
        self.assertEqual(resp.status_code, 401)

    def test_senha_fraca_e_token_adulterado_sao_recusados(self):
        self.request_reset()
        params = link_params(mail.outbox[0])
        weak = self.client.post('/api/v1/auth/password-reset/confirm/', {**params, 'new_password': '12345678'}, format='json')
        self.assertEqual(weak.status_code, 400)
        self.assertIn('new_password', weak.data)
        bad = self.client.post('/api/v1/auth/password-reset/confirm/', {**params, 'token': 'abc-123', 'new_password': NEW},
                               format='json')
        self.assertEqual(bad.status_code, 400)
        garbage = self.client.post('/api/v1/auth/password-reset/confirm/',
                                   {'uid': '@@@', 'token': 'x', 'new_password': NEW}, format='json')
        self.assertEqual(garbage.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))

    def test_falha_de_smtp_nao_vaza_nem_derruba(self):
        from unittest import mock
        with mock.patch('accounts.password_reset.send_mail', side_effect=OSError('smtp down')):
            resp = self.request_reset()
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(AuditEvent.objects.filter(action='auth.password.reset_requested', outcome='error').exists())

    def test_usuario_inativo_nao_recebe(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.request_reset().status_code, 202)
        self.assertEqual(len(mail.outbox), 0)


class SendTestEmailCommandTests(APITestCase):
    def test_recusa_quando_nada_seria_enviado(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend'):
            with self.assertRaises(CommandError):
                call_command('send_test_email', 'a@b.com')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', EMAIL_HOST='smtp.example.com')
    def test_envia_quando_ha_smtp(self):
        from unittest import mock

        from django.core.management import call_command
        with mock.patch('core.management.commands.send_test_email.send_mail') as send:
            call_command('send_test_email', 'a@b.com')
        send.assert_called_once()
