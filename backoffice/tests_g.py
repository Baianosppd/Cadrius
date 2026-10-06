"""CAD-221: TI define senha temporária → a pessoa só usa o sistema depois de trocá-la."""
from django.core.cache import cache
from rest_framework.test import APIClient

from audit.models import AuditEvent
from backoffice.services import temporary_password
from backoffice.tests import REASON, Base

PWD_OK = 'Nova-Senha-Forte-2030!'


class TempPasswordTests(Base):
    def set_temp(self, actor=None):
        return self.as_(actor or self.ti).post(f'/api/v1/backoffice/users/{self.owner.pk}/actions/',
                                               {'action': 'temp_password', 'reason': REASON}, format='json')

    def login(self, password):
        cache.clear()
        return APIClient().post('/api/v1/auth/token/', {'username': self.owner.get_username(), 'password': password}, format='json')

    def test_senha_gerada_e_forte_e_nunca_vai_para_auditoria(self):
        for _ in range(20):
            pwd = temporary_password()
            self.assertEqual(len(pwd), 16)
            self.assertFalse(set(pwd) & set('0O1lI'))
        res = self.set_temp()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res['Cache-Control'], 'no-store')
        pwd = res.data['senha_temporaria']
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(pwd))
        self.assertTrue(self.owner.must_change_password)
        self.assertTrue(res.data['usuario']['troca_de_senha_pendente'])
        event = AuditEvent.objects.filter(action='auth.password.temp_set').get()
        self.assertNotIn(pwd, str(event.changes) + event.reason)

    def test_so_ti_e_nunca_na_propria_conta(self):
        self.assertEqual(self.set_temp(self.fin).status_code, 403)
        own = self.as_(self.ti).post(f'/api/v1/backoffice/users/{self.ti.pk}/actions/',
                                     {'action': 'temp_password', 'reason': REASON}, format='json')
        self.assertEqual(own.status_code, 400)

    def test_api_bloqueada_ate_trocar_e_liberada_depois(self):
        pwd = self.set_temp().data['senha_temporaria']
        login = self.login(pwd)
        self.assertEqual(login.status_code, 200, login.data)
        self.assertTrue(login.data['password_change_required'])
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        blocked = c.get('/api/v1/contacts/')
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.data['detail'].code, 'password_change_required')
        self.assertTrue(c.get('/api/v1/auth/user/').data['must_change_password'])       # perfil continua acessível
        same = c.post('/api/v1/auth/change-password/', {'current_password': pwd, 'new_password': pwd,
                                                         'confirm_password': pwd}, format='json')
        self.assertEqual(same.status_code, 400)                                         # não pode manter a temporária
        ok = c.post('/api/v1/auth/change-password/', {'current_password': pwd, 'new_password': PWD_OK,
                                                       'confirm_password': PWD_OK}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.must_change_password)
        self.assertTrue(AuditEvent.objects.filter(action='auth.password.forced_change').exists())
        after = c.get('/api/v1/contacts/')
        self.assertNotEqual(getattr(after.data.get('detail'), 'code', ''), 'password_change_required')
        self.assertNotIn('password_change_required', self.login(PWD_OK).data)

    def test_sessoes_antigas_sao_encerradas(self):
        old = self.login('senha-que-nao-existe')
        self.assertEqual(old.status_code, 401)
        from rest_framework_simplejwt.tokens import RefreshToken
        RefreshToken.for_user(self.owner)
        self.assertEqual(self.set_temp().data['sessoes_encerradas'], 1)


class CyberTests(Base):
    URL = '/api/v1/backoffice/cyber/'

    def test_painel_completo_so_para_ti(self):
        from audit import service
        service.log('auth.login.failure', actor_type='anonymous', actor_label='d***@alfa.com')
        self.assertEqual(self.as_(self.fin).get(self.URL).status_code, 403)
        res = self.as_(self.ti).get(self.URL)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        for key in ('servidor', 'banco', 'redis', 'fila', 'ameacas', 'alertas', 'acessos', 'configuracao', 'ia', 'trilha',
                    'ips_bloqueados', 'nota', 'prioridades'):
            self.assertIn(key, data)
        self.assertNotIn('indisponivel', data['servidor'])
        self.assertGreater(data['servidor']['cpus'], 0)
        self.assertEqual(len(data['ameacas']['por_hora']), 24)
        self.assertGreaterEqual(data['ameacas']['falhas_login_24h'], 1)
        self.assertTrue(0 <= data['nota'] <= 100)
        self.assertEqual(res['Cache-Control'], 'no-store')
        self.assertNotIn('dono@alfa.com', res.content.decode())          # e-mails sempre mascarados

    def test_nota_cai_com_problema_grave(self):
        from backoffice import cyber
        nota, prioridades = cyber.score({'banco': {'indisponivel': True}, 'alertas': {'por_gravidade': {'critical': 1}},
                                         'acessos': {'equipe_sem_mfa': ['t***@x']}})
        self.assertLessEqual(nota, 40)
        self.assertEqual(prioridades[0]['nivel'], 'critico')

    def test_bloqueio_de_ip_barra_o_acesso_e_e_auditado(self):
        ti = self.as_(self.ti)
        bad = ti.post(f'{self.URL}blocked-ips/', {'rede': '10.0.0.5', 'reason': REASON}, format='json')
        self.assertEqual(bad.status_code, 400)                              # rede interna
        self.assertEqual(ti.post(f'{self.URL}blocked-ips/', {'rede': 'abc', 'reason': REASON}, format='json').status_code, 400)
        self.assertEqual(ti.post(f'{self.URL}blocked-ips/', {'rede': '203.0.0.0/8', 'reason': REASON}, format='json').status_code, 400)
        own = ti.post(f'{self.URL}blocked-ips/', {'rede': '45.33.32.156', 'reason': REASON}, format='json',
                      REMOTE_ADDR='45.33.32.156')
        self.assertEqual(own.status_code, 400)                              # o próprio IP
        ok = ti.post(f'{self.URL}blocked-ips/', {'rede': '185.220.101.0/24', 'reason': REASON, 'horas': 24}, format='json')
        self.assertEqual(ok.status_code, 201, ok.data)
        blocked = APIClient().get('/api/v1/auth/user/', REMOTE_ADDR='185.220.101.77')
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()['code'], 'ip_blocked')
        self.assertNotEqual(APIClient().get('/api/v1/auth/user/', REMOTE_ADDR='45.33.32.1').status_code, 403)
        from audit.models import AuditEvent, BlockedIP
        self.assertEqual(BlockedIP.objects.get().hits, 1)
        self.assertTrue(AuditEvent.objects.filter(action='security.ip_blocked').exists())
        self.assertEqual(ti.delete(f'{self.URL}blocked-ips/{ok.data["id"]}/').status_code, 204)
        self.assertNotEqual(APIClient().get('/api/v1/auth/user/', REMOTE_ADDR='185.220.101.77').status_code, 403)

    def test_ip_falsificado_no_cabecalho_nao_engana(self):
        from django.test import RequestFactory, override_settings

        from audit.context import client_ip
        req = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='1.2.3.4, 198.51.100.9', REMOTE_ADDR='10.0.0.2')
        with override_settings(AXES_IPWARE_PROXY_COUNT=1):
            self.assertEqual(client_ip(req), '198.51.100.9')               # o que o Traefik acrescentou, não o do cliente

    def test_triagem_de_alerta(self):
        from audit.models import AnomalyAlert
        alert = AnomalyAlert.objects.create(rule='A1', severity='high', summary='x', dedupe_key='k1')
        res = self.as_(self.ti).post(f'{self.URL}alerts/{alert.pk}/review/', {'status': 'resolved'}, format='json')
        self.assertEqual(res.status_code, 200)
        alert.refresh_from_db()
        self.assertEqual(alert.status, 'resolved')
