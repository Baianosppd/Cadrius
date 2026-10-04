from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from cadrius.tests_security import make_org, make_user
from research import cnj, monitor
from research.models import CaseMovement, MonitoredCase, NewsItem
from research.news import parse_feed
from research.providers import datajud

VALID = '0000832-35.2018.4.01.3202'   # dígito verificador calculado em make_valid()


def make_valid(seq='0000832', year='2018', j='4', tr='01', origin='3202'):
    return f'{seq}-{cnj.check_digits(seq, year, j, tr, origin)}.{year}.{j}.{tr}.{origin}'


def datajud_payload(*moves):
    return {'hits': {'hits': [{'_source': {'classe': {'nome': 'Procedimento Comum'}, 'orgaoJulgador': {'nome': '1ª Vara'},
                                           'movimentos': [{'codigo': c, 'nome': n, 'dataHora': d} for c, n, d in moves]}}]}}


class CNJTests(SimpleTestCase):
    def test_parse_valid_and_invalid(self):
        number = make_valid()
        self.assertEqual(cnj.parse(number)['formatted'], number)
        self.assertEqual(cnj.parse(number.replace('.', '').replace('-', ''))['formatted'], number)
        bad = number[:8] + ('00' if number[8:10] != '00' else '01') + number[10:]
        self.assertIsNone(cnj.parse(bad))
        self.assertIsNone(cnj.parse('123'))

    def test_tribunal_alias(self):
        self.assertEqual(cnj.tribunal_alias(cnj.parse(make_valid(j='8', tr='26', origin='0100'))), 'tjsp')
        self.assertEqual(cnj.tribunal_alias(cnj.parse(make_valid(j='4', tr='01'))), 'trf1')
        self.assertEqual(cnj.tribunal_alias(cnj.parse(make_valid(j='5', tr='02'))), 'trt2')
        self.assertIsNone(cnj.tribunal_alias(cnj.parse(make_valid(j='6', tr='26'))))


class NewsTests(SimpleTestCase):
    def test_parse_rss_and_atom(self):
        rss = b'<rss><channel><item><title>A <b>x</b></title><link>https://e.com/a</link><pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate><description>Resumo</description></item></channel></rss>'
        items = parse_feed(rss)
        self.assertEqual(items[0]['title'], 'A x')
        self.assertIsNotNone(items[0]['published_at'])
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>B</title><link href="https://e.com/b"/><updated>2026-10-05T10:00:00Z</updated></entry></feed>'
        self.assertEqual(parse_feed(atom)[0]['url'], 'https://e.com/b')

    def test_rejects_entities_and_bad_links(self):
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>')
        self.assertEqual(parse_feed(b'<rss><item><title>T</title><link>javascript:x</link></item></rss>'), [])


@override_settings(DATAJUD_API_KEY='k')
class MonitorAndApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.user = make_user('a@a.com', self.org, role='OWNER')
        self.other_org = make_org()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.number = make_valid()

    def _add(self):
        return self.client.post('/api/v1/research/cases/', {'cnj': self.number, 'label': 'Cliente João'}, format='json')

    def test_create_validates_dedupes_and_isolates(self):
        self.assertEqual(self.client.post('/api/v1/research/cases/', {'cnj': '123'}, format='json').status_code, 400)
        r = self._add()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['tribunal'], 'trf1')
        self.assertEqual(self._add().status_code, 409)
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT cnj FROM research_monitoredcase')
            self.assertTrue(cur.fetchone()[0].startswith('enc::'))   # cifrado no banco
        other = make_user('b@b.com', self.other_org, role='OWNER')
        c2 = APIClient()
        c2.force_authenticate(other)
        self.assertEqual(c2.get('/api/v1/research/cases/').json(), [])
        self.assertEqual(c2.get(f'/api/v1/research/cases/{r.json()["id"]}/').status_code, 404)

    @mock.patch('research.providers.datajud.requests.post')
    def test_first_sync_silent_then_notifies_new(self, post):
        case_id = self._add().json()['id']
        post.return_value = mock.Mock(status_code=200, json=lambda: datajud_payload(('26', 'Distribuição', '2026-01-01T10:00:00Z')))
        with mock.patch('research.monitor._notify') as notify:
            res = self.client.post(f'/api/v1/research/cases/{case_id}/check-now/')
            self.assertEqual(res.json()['new'], 1)
            notify.assert_not_called()                      # 1ª consulta: só grava histórico
            post.return_value = mock.Mock(status_code=200, json=lambda: datajud_payload(
                ('26', 'Distribuição', '2026-01-01T10:00:00Z'), ('123', 'Juntada', '2026-02-01T10:00:00Z')))
            res = self.client.post(f'/api/v1/research/cases/{case_id}/check-now/')
            self.assertEqual(res.json()['new'], 1)
            notify.assert_called_once()
            self.assertEqual(self.client.post(f'/api/v1/research/cases/{case_id}/check-now/').json()['new'], 0)  # idempotente
        self.assertEqual(CaseMovement.objects.filter(case_id=case_id).count(), 2)

    @mock.patch('research.providers.datajud.requests.post')
    def test_not_found_and_provider_errors_are_recorded(self, post):
        case_id = self._add().json()['id']
        post.return_value = mock.Mock(status_code=200, json=lambda: {'hits': {'hits': []}})
        self.assertIn('não encontrado', self.client.post(f'/api/v1/research/cases/{case_id}/check-now/').json()['error'])
        post.return_value = mock.Mock(status_code=403, json=lambda: {})
        self.assertIn('recusou', self.client.post(f'/api/v1/research/cases/{case_id}/check-now/').json()['error'])

    def test_missing_key_is_clear_error(self):
        with override_settings(DATAJUD_API_KEY=''):
            with self.assertRaises(datajud.ProviderError):
                datajud.search_case('0' * 20, 'trf1')

    def test_delete_and_check_all(self):
        case_id = self._add().json()['id']
        with mock.patch('research.monitor.check_case', return_value={'new': 2, 'error': ''}):
            self.assertEqual(monitor.check_all(), {'cases': 1, 'new': 2, 'errors': 0})
        self.assertEqual(self.client.delete(f'/api/v1/research/cases/{case_id}/').status_code, 204)
        self.assertEqual(MonitoredCase.objects.count(), 0)

    def test_news_endpoint(self):
        NewsItem.objects.create(source='X', url='https://e.com/1', title='T')
        self.assertEqual(self.client.get('/api/v1/research/news/').json()[0]['title'], 'T')
