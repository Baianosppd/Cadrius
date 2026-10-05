from datetime import date

from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

from cadrius.tests_security import make_org, make_user
from forense.calendar import Calendar, easter, national_closures
from forense.models import Holiday


class CalendarTests(APITestCase):
    def test_pascoa_e_feriados_moveis(self):
        self.assertEqual([easter(y) for y in (2024, 2025, 2026)], [date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5)])
        days = national_closures(2026)
        for d in (date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3), date(2026, 6, 4), date(2026, 11, 20)):
            self.assertIn(d, days)
        self.assertNotIn(date(2026, 8, 11), days)
        self.assertIn(date(2026, 8, 11), national_closures(2026, federal=True))       # Lei 5.010/66 só na Justiça Federal

    def test_contagem_cpc_224(self):
        cal = Calendar()
        r = cal.count(date(2026, 3, 2), 15)
        self.assertEqual(r['vencimento'], date(2026, 3, 23))                          # exclui o começo, só dias úteis
        self.assertEqual(cal.count(date(2026, 2, 12), 3)['vencimento'], date(2026, 2, 19))   # pula fim de semana e Carnaval
        self.assertIn('Carnaval (segunda-feira)', [p['motivo'] for p in cal.count(date(2026, 2, 12), 3)['pulados']])
        self.assertEqual(cal.count(date(2026, 12, 18), 1)['vencimento'], date(2027, 1, 21))  # recesso 20/12–20/01 (art. 220)
        self.assertEqual(Calendar(tribunal='trf3').count(date(2026, 8, 10), 1)['vencimento'], date(2026, 8, 12))

    def test_disponibilizacao_no_diario(self):
        r = Calendar().count(date(2026, 3, 6), 5, from_availability=True)            # sexta: publica na segunda
        self.assertEqual(r['publicacao'], date(2026, 3, 9))
        self.assertEqual(r['vencimento'], date(2026, 3, 16))

    def test_feriados_do_escritorio_por_tribunal_e_anuais(self):
        org = make_org()
        Holiday.objects.create(organization=org, date=date(2026, 3, 3), name='Feriado do TJ', tribunal='tjsp')
        Holiday.objects.create(organization=org, date=date(2020, 1, 25), name='Aniversário de SP', yearly=True)
        self.assertEqual(Calendar(org, 'tjsp').count(date(2026, 3, 2), 1)['vencimento'], date(2026, 3, 4))
        self.assertEqual(Calendar(org, 'trt2').count(date(2026, 3, 2), 1)['vencimento'], date(2026, 3, 3))
        self.assertFalse(Calendar(org).is_business_day(date(2027, 1, 25)))
        self.assertEqual(Calendar().back(date(2026, 2, 19), 2), date(2026, 2, 13))
        self.assertEqual(Calendar().add(date(2026, 2, 14), 0), date(2026, 2, 18))

    def test_limites(self):
        with self.assertRaises(ValueError):
            Calendar().count(date(2026, 3, 2), 0)
        with self.assertRaises(ValueError):
            Calendar().count(date(2026, 3, 2), 366)


class ForenseApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()

    def test_prazo(self):
        self.c.force_authenticate(self.member)
        res = self.c.get('/api/v1/forense/prazo/', {'inicio': '2026-03-06', 'dias': 5, 'disponibilizacao': '1'})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()['publicacao'], res.json()['vencimento']), ('2026-03-09', '2026-03-16'))
        self.assertIn('aviso', res.json())
        self.assertEqual(self.c.get('/api/v1/forense/prazo/', {'inicio': 'ontem', 'dias': 5}).status_code, 400)
        self.assertIn('Prazo entre', self.c.get('/api/v1/forense/prazo/', {'inicio': '2026-03-06', 'dias': 900}).json()['detail'])
        self.c.force_authenticate(None)
        self.assertEqual(self.c.get('/api/v1/forense/prazo/', {'inicio': '2026-03-06', 'dias': 5}).status_code, 401)

    def test_feriados_so_dono_admin_cadastram_e_isolamento(self):
        self.c.force_authenticate(self.member)
        body = {'data': '2026-03-03', 'nome': 'Feriado municipal', 'tribunal': 'TJSP'}
        self.assertEqual(self.c.post('/api/v1/forense/feriados/', body, format='json').status_code, 403)
        self.c.force_authenticate(self.owner)
        res = self.c.post('/api/v1/forense/feriados/', body, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['tribunal'], 'tjsp')
        self.assertEqual(self.c.post('/api/v1/forense/feriados/', {'data': 'x', 'nome': 'abc'}, format='json').status_code, 400)
        self.c.force_authenticate(self.member)
        self.assertEqual(len(self.c.get('/api/v1/forense/feriados/').json()), 1)
        r = self.c.get('/api/v1/forense/prazo/', {'inicio': '2026-03-02', 'dias': 1, 'tribunal': 'tjsp'})
        self.assertEqual(r.json()['vencimento'], '2026-03-04')
        other = make_user('outro@y.com', make_org('Outro'), role='OWNER')
        self.c.force_authenticate(other)
        self.assertEqual(self.c.get('/api/v1/forense/feriados/').json(), [])
        self.assertEqual(self.c.delete(f'/api/v1/forense/feriados/{res.json()["id"]}/').status_code, 404)
        self.c.force_authenticate(self.owner)
        self.assertEqual(self.c.delete(f'/api/v1/forense/feriados/{res.json()["id"]}/').status_code, 204)
