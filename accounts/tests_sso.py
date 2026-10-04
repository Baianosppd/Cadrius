from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings

from accounts.models import OrganizationMembership, SocialIdentity
from accounts.sso import STATE_COOKIE
from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user

User = get_user_model()
CFG = dict(GOOGLE_CLIENT_ID='gid', GOOGLE_CLIENT_SECRET='gsecret', MICROSOFT_CLIENT_ID='mid',
           MICROSOFT_CLIENT_SECRET='msecret', FRONTEND_URL='https://app.example.com', API_PUBLIC_URL='https://api.example.com')


def fragment(response):
    return {k: v[0] for k, v in parse_qs(urlparse(response['Location']).fragment).items()}


@override_settings(**CFG)
class SsoTests(TestCase):
    def start(self, provider='google'):
        resp = self.client.get(f'/api/v1/auth/{provider}/')
        self.assertEqual(resp.status_code, 302, resp)
        return resp, parse_qs(urlparse(resp['Location']).query)

    def callback(self, provider='google', claims=None, state=None, code='abc'):
        """Percorre o fluxo inteiro; só a rede (troca do code e JWKS) é simulada."""
        _, q = self.start(provider)
        cookie = signing.loads(self.client.cookies[STATE_COOKIE].value, salt='cadrius.sso')
        claims = claims or {}
        with mock.patch('accounts.sso._exchange_code', return_value={'id_token': 'x'}) as ex, \
                mock.patch('accounts.sso._verify_id_token', return_value=claims) as ver:
            resp = self.client.get(f'/api/v1/auth/{provider}/callback/',
                                   {'state': state or q['state'][0], 'code': code})
        return resp, ex, ver, cookie

    # ---- início do fluxo
    def test_start_redireciona_com_state_nonce_e_pkce_e_cookie_httponly(self):
        resp, q = self.start()
        self.assertTrue(resp['Location'].startswith('https://accounts.google.com/o/oauth2/v2/auth?'))
        self.assertEqual(q['client_id'], ['gid'])
        self.assertEqual(q['redirect_uri'], ['https://api.example.com/api/v1/auth/google/callback/'])
        self.assertEqual(q['code_challenge_method'], ['S256'])
        for k in ('state', 'nonce', 'code_challenge'):
            self.assertTrue(q[k][0])
        morsel = self.client.cookies[STATE_COOKIE]
        self.assertTrue(morsel['httponly'])
        self.assertEqual(morsel['samesite'], 'Lax')

    def test_provedor_nao_configurado_volta_ao_front_com_erro(self):
        with override_settings(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET=''):
            resp = self.client.get('/api/v1/auth/google/')
        self.assertEqual(fragment(resp), {'error': 'sso_disabled'})

    def test_rota_do_sso_nao_engole_as_demais_rotas_de_auth(self):
        self.assertEqual(self.client.get('/api/v1/auth/user/').status_code, 401)
        self.assertEqual(self.client.post('/api/v1/auth/register/', {}, content_type='application/json').status_code, 400)

    # ---- callback: caminhos felizes
    def test_conta_existente_com_email_verificado_entra_e_vincula_identidade(self):
        user = make_user('ana@example.com', make_org(), role='OWNER')
        resp, ex, _, cookie = self.callback(claims={'sub': 'g-1', 'email': 'Ana@Example.com', 'email_verified': True})
        frag = fragment(resp)
        self.assertTrue(resp['Location'].startswith('https://app.example.com/google/callback#'))
        self.assertTrue(frag['access'] and frag['refresh'])
        self.assertNotIn('?', resp['Location'])  # tokens só no fragmento
        self.assertEqual(ex.call_args.args[3], cookie['v'])  # PKCE verifier enviado na troca
        self.assertTrue(SocialIdentity.objects.filter(user=user, provider='google', subject='g-1').exists())
        self.assertTrue(AuditEvent.objects.filter(action='auth.sso.login', outcome='success').exists())
        self.assertEqual(resp['Cache-Control'], 'no-store')
        # token realmente funciona na API
        me = self.client.get('/api/v1/auth/user/', HTTP_AUTHORIZATION=f"Bearer {frag['access']}")
        self.assertEqual(me.status_code, 200)

    def test_login_seguinte_usa_a_identidade_mesmo_se_o_email_mudar(self):
        user = make_user('ana@example.com')
        SocialIdentity.objects.create(user=user, provider='google', subject='g-1')
        resp, *_ = self.callback(claims={'sub': 'g-1', 'email': 'outro@example.com', 'email_verified': False})
        self.assertIn('access', fragment(resp))

    def test_dominio_de_escritorio_cadastrado_cria_membro(self):
        org = make_org()
        org.allowed_domain = 'banca.adv.br'
        org.save()
        resp, *_ = self.callback(claims={'sub': 'g-9', 'email': 'novo@banca.adv.br', 'email_verified': True,
                                         'given_name': 'Novo', 'family_name': 'Adv'})
        self.assertIn('access', fragment(resp))
        user = User.objects.get(email='novo@banca.adv.br')
        self.assertFalse(user.has_usable_password())
        self.assertEqual(OrganizationMembership.objects.get(user=user).organization_id, org.pk)
        self.assertEqual(OrganizationMembership.objects.get(user=user).role, 'MEMBER')

    def test_microsoft_exige_xms_edov_para_vincular_por_email(self):
        make_user('ana@example.com')
        claims = {'sub': 's', 'oid': 'o1', 'tid': 't1', 'email': 'ana@example.com'}
        resp, *_ = self.callback('microsoft', claims=claims)
        self.assertEqual(fragment(resp), {'error': 'email_unverified'})
        resp, *_ = self.callback('microsoft', claims={**claims, 'xms_edov': True})
        self.assertIn('access', fragment(resp))
        self.assertTrue(SocialIdentity.objects.filter(provider='microsoft', subject='t1:o1').exists())

    # ---- callback: recusas
    def test_email_nao_verificado_nao_sequestra_conta(self):
        make_user('ana@example.com')
        resp, *_ = self.callback(claims={'sub': 'g-1', 'email': 'ana@example.com', 'email_verified': False})
        self.assertEqual(fragment(resp), {'error': 'email_unverified'})
        self.assertFalse(SocialIdentity.objects.exists())
        self.assertTrue(AuditEvent.objects.filter(action='auth.sso.login', outcome='denied').exists())

    def test_sem_conta_e_dominio_publico_nao_cria_usuario(self):
        resp, *_ = self.callback(claims={'sub': 'g-2', 'email': 'alguem@gmail.com', 'email_verified': True})
        self.assertEqual(fragment(resp), {'error': 'no_account'})
        self.assertFalse(User.objects.filter(email='alguem@gmail.com').exists())

    def test_dominio_corporativo_sem_escritorio_nao_cria_usuario(self):
        resp, *_ = self.callback(claims={'sub': 'g-3', 'email': 'x@semescritorio.com', 'email_verified': True})
        self.assertEqual(fragment(resp), {'error': 'no_account'})

    def test_usuario_inativo_e_recusado(self):
        user = make_user('ana@example.com')
        user.is_active = False
        user.save()
        resp, *_ = self.callback(claims={'sub': 'g-1', 'email': 'ana@example.com', 'email_verified': True})
        self.assertEqual(fragment(resp), {'error': 'account_disabled'})

    def test_state_diferente_ou_ausente_e_recusado_sem_chamar_o_provedor(self):
        with mock.patch('accounts.sso._exchange_code') as ex:
            self.start()
            resp = self.client.get('/api/v1/auth/google/callback/', {'state': 'forjado', 'code': 'abc'})
            self.assertEqual(fragment(resp), {'error': 'state_invalid'})
            self.client.cookies.clear()
            resp = self.client.get('/api/v1/auth/google/callback/', {'state': 'x', 'code': 'abc'})
            self.assertEqual(fragment(resp), {'error': 'state_invalid'})
            ex.assert_not_called()

    def test_cookie_de_outro_provedor_e_recusado(self):
        _, q = self.start('google')
        resp = self.client.get('/api/v1/auth/microsoft/callback/', {'state': q['state'][0], 'code': 'abc'})
        self.assertEqual(fragment(resp), {'error': 'state_invalid'})

    def test_provedor_negou_acesso(self):
        self.start()
        resp = self.client.get('/api/v1/auth/google/callback/', {'error': 'access_denied'})
        self.assertEqual(fragment(resp), {'error': 'access_denied'})

    def test_id_token_invalido_ou_provedor_fora_do_ar(self):
        from accounts.sso import SsoError
        _, q = self.start()
        with mock.patch('accounts.sso._exchange_code', return_value={'id_token': 'x'}), \
                mock.patch('accounts.sso._verify_id_token', side_effect=SsoError('token_invalid')):
            resp = self.client.get('/api/v1/auth/google/callback/', {'state': q['state'][0], 'code': 'abc'})
        self.assertEqual(fragment(resp), {'error': 'token_invalid'})
        _, q = self.start()
        with mock.patch('accounts.sso._exchange_code', side_effect=SsoError('provider_unreachable')):
            resp = self.client.get('/api/v1/auth/google/callback/', {'state': q['state'][0], 'code': 'abc'})
        self.assertEqual(fragment(resp), {'error': 'provider_unreachable'})


class IdTokenValidationTests(TestCase):
    """Valida de verdade a assinatura/claims (chave RSA gerada no teste; só o JWKS é simulado)."""

    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(self, **over):
        import time

        import jwt
        claims = {'iss': 'https://accounts.google.com', 'aud': 'gid', 'sub': '1', 'exp': int(time.time()) + 300,
                  'nonce': 'n1', 'email': 'a@x.com', 'email_verified': True, **over}
        return jwt.encode(claims, self.key, algorithm='RS256')

    def verify(self, token, nonce='n1'):
        from accounts.sso import _verify_id_token
        with override_settings(**CFG), mock.patch('accounts.sso.jwt.PyJWKClient') as client:
            client.return_value.get_signing_key_from_jwt.return_value.key = self.key.public_key()
            return _verify_id_token('google', token, nonce)

    def test_aceita_token_valido(self):
        self.assertEqual(self.verify(self.token())['sub'], '1')

    def test_recusa_audience_issuer_nonce_e_expirado(self):
        from accounts.sso import SsoError
        for bad, nonce in ((self.token(aud='outro'), 'n1'), (self.token(iss='https://evil.example'), 'n1'),
                           (self.token(), 'outro-nonce'), (self.token(exp=1), 'n1')):
            with self.assertRaises(SsoError) as ctx:
                self.verify(bad, nonce)
            self.assertEqual(ctx.exception.code, 'token_invalid')
