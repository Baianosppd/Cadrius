"""CAD-232: "Manter conectado" — sessão de 30 dias que se renova no uso; sem marcar, 1 dia."""

from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from cadrius.tests_security import make_org, make_user

PWD = 'Str0ng-Passw0rd!x'


class RememberMeTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user('adv@x.com', make_org('Escritório'), role='OWNER')
        self.c = APIClient()

    def login(self, **extra):
        res = self.c.post('/api/v1/auth/token/', {'username': 'adv@x.com', 'password': PWD, **extra}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def days(self, refresh):
        t = RefreshToken(refresh)
        return (t['exp'] - t['iat']) / 86400

    def test_manter_conectado_vale_30_dias_e_renova_no_uso(self):
        tokens = self.login(lembrar=True)
        self.assertAlmostEqual(self.days(tokens['refresh']), 30, delta=0.01)
        res = self.c.post('/api/v1/auth/token/refresh/', {'refresh': tokens['refresh']}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        new = res.json()['refresh']
        self.assertAlmostEqual(self.days(new), 30, delta=0.01)          # a renovação mantém os 30 dias
        old = self.c.post('/api/v1/auth/token/refresh/', {'refresh': tokens['refresh']}, format='json')
        self.assertEqual(old.status_code, 401)                           # o token antigo não vale mais

    def test_sem_marcar_vale_um_dia(self):
        tokens = self.login(lembrar=False)
        self.assertAlmostEqual(self.days(tokens['refresh']), 1, delta=0.01)
        res = self.c.post('/api/v1/auth/token/refresh/', {'refresh': tokens['refresh']}, format='json').json()
        self.assertAlmostEqual(self.days(res['refresh']), 1, delta=0.01)

    def test_equipe_cadrius_nunca_fica_lembrada(self):
        self.user.is_staff = True
        self.user.save()
        tokens = self.login(lembrar=True)
        self.assertLessEqual(self.days(tokens['refresh']), 1.01)

    def test_sair_derruba_a_sessao_longa(self):
        tokens = self.login(lembrar=True)
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.c.post('/api/v1/auth/logout/', {'refresh': tokens['refresh']}, format='json')
        self.c.credentials()
        self.assertEqual(self.c.post('/api/v1/auth/token/refresh/', {'refresh': tokens['refresh']}, format='json').status_code, 401)
