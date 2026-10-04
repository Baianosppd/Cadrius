"""CAD-169: verificação em duas etapas (TOTP) — cadastro, login em 2 passos, recuperação, SSO e exigência para a equipe."""
import base64
import time
from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from accounts import mfa
from accounts.models import MFADevice
from accounts.tests_sso import CFG, SsoTests, fragment
from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user

PASSWORD = 'Str0ng-Passw0rd!x'


class TotpTests(SimpleTestCase):
    def test_vetores_da_rfc_6238(self):
        secret = base64.b32encode(b'12345678901234567890').decode()
        self.assertEqual(mfa.code_at(secret, 59 // 30), '287082')
        self.assertEqual(mfa.code_at(secret, 1111111109 // 30), '081804')
        self.assertEqual(mfa.code_at(secret, 2000000000 // 30), '279037')

    def test_janela_de_um_passo_e_formato(self):
        secret = mfa.new_secret()
        now = 1_700_000_000
        self.assertIsNotNone(mfa.matching_step(secret, mfa.code_at(secret, now // 30 - 1), now))
        self.assertIsNone(mfa.matching_step(secret, mfa.code_at(secret, now // 30 - 3), now))
        self.assertIsNone(mfa.matching_step(secret, '12345', now))
        self.assertIn('otpauth://totp/Cadrius%3Aana%40x.com?secret=', mfa.otpauth_uri(secret, 'ana@x.com'))
        self.assertTrue(mfa.qr_svg('otpauth://x').lstrip().startswith('<svg'))


def current_code(user):
    return mfa.code_at(MFADevice.objects.get(user=user).secret, int(time.time() // 30))


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.user = make_user('ana@x.com', self.org, role='OWNER')
        self.client = APIClient()

    def enroll(self, user=None):
        """Cadastra o MFA pelo fluxo real; devolve os códigos de recuperação."""
        user = user or self.user
        client = APIClient()
        client.force_authenticate(user)
        setup = client.post('/api/v1/auth/mfa/setup/').json()
        self.assertIn('<svg', setup['qr_svg'])
        res = client.post('/api/v1/auth/mfa/confirm/', {'code': mfa.code_at(setup['secret'], int(time.time() // 30))}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        MFADevice.objects.filter(user=user).update(last_step=0)   # o teste reutiliza o passo atual a seguir
        return res.json()

    def login(self, email='ana@x.com'):
        return self.client.post('/api/v1/auth/token/', {'username': email, 'password': PASSWORD}, format='json')


class EnrollTests(Base):
    def test_cadastro_confirma_com_codigo_e_entrega_codigos_de_recuperacao(self):
        data = self.enroll()
        self.assertEqual(len(data['recovery_codes']), 10)
        self.assertTrue(data['enabled'])
        self.assertTrue(mfa.enabled(self.user))
        self.assertTrue(AuditEvent.objects.filter(action='auth.mfa.enabled').exists())
        # tokens devolvidos na confirmação já valem como sessão MFA
        me = self.client.get('/api/v1/auth/mfa/', HTTP_AUTHORIZATION=f"Bearer {data['access']}").json()
        self.assertTrue(me['session_has_mfa'])

    def test_codigo_errado_nao_ativa_e_reconfigurar_exige_desativar(self):
        self.client.force_authenticate(self.user)
        self.client.post('/api/v1/auth/mfa/setup/')
        self.assertEqual(self.client.post('/api/v1/auth/mfa/confirm/', {'code': '000000'}, format='json').status_code, 400)
        self.assertFalse(mfa.enabled(self.user))
        self.enroll()
        self.assertEqual(self.client.post('/api/v1/auth/mfa/setup/').status_code, 409)

    def test_segredo_cifrado_no_banco(self):
        self.enroll()
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT secret FROM accounts_mfadevice')
            self.assertTrue(cur.fetchone()[0].startswith('enc::'))


class LoginTests(Base):
    def test_sem_mfa_login_direto(self):
        res = self.login().json()
        self.assertIn('access', res)
        self.assertNotIn('mfa_setup_required', res)

    def test_com_mfa_login_em_dois_passos_e_marca_amr(self):
        self.enroll()
        first = self.login().json()
        self.assertEqual(set(first), {'mfa_required', 'mfa_token'})
        res = self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': first['mfa_token'], 'code': current_code(self.user)}, format='json')
        self.assertEqual(res.status_code, 200)
        from rest_framework_simplejwt.tokens import AccessToken
        self.assertEqual(AccessToken(res.json()['access'])['amr'], 'mfa')
        # o refresh mantém a marca
        refreshed = self.client.post('/api/v1/auth/token/refresh/', {'refresh': res.json()['refresh']}, format='json').json()
        self.assertEqual(AccessToken(refreshed['access'])['amr'], 'mfa')
        # desafio é de uso único e o mesmo código não vale duas vezes
        again = self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': first['mfa_token'], 'code': current_code(self.user)}, format='json')
        self.assertEqual(again.json()['code'], 'mfa_expired')
        second = self.login().json()
        replay = self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': second['mfa_token'], 'code': current_code(self.user)}, format='json')
        self.assertEqual(replay.json()['code'], 'mfa_invalid')

    def test_cinco_erros_invalidam_o_desafio(self):
        self.enroll()
        token = self.login().json()['mfa_token']
        for _ in range(4):
            self.assertEqual(self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': token, 'code': '000000'}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': token, 'code': '000000'}, format='json').status_code, 401)
        res = self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': token, 'code': current_code(self.user)}, format='json')
        self.assertEqual(res.json()['code'], 'mfa_expired')
        self.assertEqual(AuditEvent.objects.filter(action='auth.mfa.failed').count(), 5)

    def test_desafio_adulterado_ou_vencido(self):
        self.enroll()
        self.assertEqual(self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': 'x', 'code': '1'}, format='json').status_code, 401)
        token = self.login().json()['mfa_token']
        with mock.patch('accounts.mfa.CHALLENGE_MAX_AGE', -1):
            self.assertEqual(self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': token, 'code': current_code(self.user)},
                                              format='json').status_code, 401)

    def test_codigo_de_recuperacao_vale_uma_vez(self):
        codes = self.enroll()['recovery_codes']
        token = self.login().json()['mfa_token']
        res = self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': token, 'code': codes[0].upper()}, format='json').json()
        self.assertEqual(res['recovery_codes_left'], 9)
        token = self.login().json()['mfa_token']
        self.assertEqual(self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': token, 'code': codes[0]}, format='json').status_code, 400)


class ManageTests(Base):
    def test_desativar_exige_senha_e_codigo(self):
        codes = self.enroll()['recovery_codes']
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post('/api/v1/auth/mfa/disable/', {'password': 'errada', 'code': codes[0]}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/v1/auth/mfa/disable/', {'password': PASSWORD, 'code': '000000'}, format='json').status_code, 400)
        self.assertFalse(self.client.post('/api/v1/auth/mfa/disable/', {'password': PASSWORD, 'code': codes[1]}, format='json').json()['enabled'])
        self.assertIn('access', self.login().json())

    def test_novos_codigos_de_recuperacao(self):
        old = self.enroll()['recovery_codes']
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post('/api/v1/auth/mfa/recovery-codes/', {'code': old[0]}, format='json').status_code, 400)  # pede o app
        new = self.client.post('/api/v1/auth/mfa/recovery-codes/', {'code': current_code(self.user)}, format='json').json()['recovery_codes']
        self.assertEqual(len(set(new) & set(old)), 0)

    def test_perfil_mostra_estado(self):
        self.client.force_authenticate(self.user)
        me = self.client.get('/api/v1/auth/user/').json()
        self.assertEqual((me['mfa_enabled'], me['mfa_required']), (False, False))
        with override_settings(MFA_REQUIRED_FOR_MANAGERS=True):
            self.assertTrue(self.client.get('/api/v1/auth/user/').json()['mfa_required'])


class StaffTests(Base):
    def setUp(self):
        super().setUp()
        self.staff = make_user('ti@cadrius.ia.br')
        self.staff.is_staff = True
        self.staff.save()
        self.staff.groups.add(Group.objects.get_or_create(name='Cadrius TI')[0])
        from privacy.tests.test_privacy import accept_all
        accept_all(self.staff)   # com token real, termos pendentes dariam 428 antes do MFA

    def test_equipe_sem_mfa_entra_no_app_mas_nao_na_gestao(self):
        res = self.login('ti@cadrius.ia.br').json()
        self.assertTrue(res['mfa_setup_required'])
        denied = self.client.get('/api/v1/backoffice/me/', HTTP_AUTHORIZATION=f"Bearer {res['access']}")
        self.assertEqual((denied.status_code, denied.json()['code']), (403, 'mfa_required'))

    def test_equipe_com_mfa_entra_na_gestao(self):
        self.enroll(self.staff)
        token = self.login('ti@cadrius.ia.br').json()['mfa_token']
        access = self.client.post('/api/v1/auth/mfa/verify/', {'mfa_token': token, 'code': current_code(self.staff)}, format='json').json()['access']
        self.assertEqual(self.client.get('/api/v1/backoffice/me/', HTTP_AUTHORIZATION=f'Bearer {access}').json()['areas'], ['ti'])

    def test_ti_redefine_mfa_de_quem_perdeu_o_celular(self):
        self.enroll()
        ti = APIClient()
        ti.force_authenticate(self.staff, token={'amr': 'mfa'})
        url = f'/api/v1/backoffice/users/{self.user.pk}/actions/'
        self.assertEqual(ti.post(url, {'action': 'reset_mfa', 'reason': 'curto'}, format='json').status_code, 400)
        res = ti.post(url, {'action': 'reset_mfa', 'reason': 'Perdeu o celular, confirmado por telefone'}, format='json').json()
        self.assertFalse(res['mfa'])
        self.assertFalse(mfa.enabled(self.user))
        self.assertTrue(AuditEvent.objects.filter(action='auth.mfa.reset').exists())
        self.assertEqual(ti.post(url, {'action': 'reset_mfa', 'reason': 'Perdeu o celular de novo'}, format='json').status_code, 400)


@override_settings(**CFG)
class SsoMfaTests(TestCase):
    """Reaproveita o fluxo de SSO: com MFA ativo, o callback devolve um desafio em vez dos tokens."""

    start, callback, enroll = SsoTests.start, SsoTests.callback, Base.enroll

    def test_sso_com_mfa_pede_o_codigo(self):
        user = make_user('bia@example.com', make_org(), role='OWNER')
        self.enroll(user)
        resp, *_ = self.callback(claims={'sub': 'g-9', 'email': 'bia@example.com', 'email_verified': True})
        frag = fragment(resp)
        self.assertEqual(set(frag), {'mfa_token'})
        res = APIClient().post('/api/v1/auth/mfa/verify/', {'mfa_token': frag['mfa_token'], 'code': current_code(user)}, format='json')
        self.assertIn('access', res.json())
