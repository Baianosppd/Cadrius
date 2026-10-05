from datetime import date
from unittest import mock

from django.core.cache import cache
from django.db import connection
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from automations import catalog, engine
from automations.models import Rule
from automations.templates import TEMPLATES
from cadrius.tests_security import make_org, make_user
from publications import services
from publications.models import OabWatch, Publication
from publications.providers import djen
from publications.triage import local_triage
from research.models import MonitoredCase
from tasks.models import UserTask

CNJ = '0000832-35.2018.4.01.3202'
SENTENCA = ('<p>Vistos.</p><p>Ante o exposto, JULGO PROCEDENTE o pedido &amp; condeno o réu.</p><br>Intimem-se.')


def item(id_=1, texto=SENTENCA, day='2026-03-06', **kw):
    return {'id': id_, 'data_disponibilizacao': day, 'siglaTribunal': 'TRF1', 'tipoComunicacao': 'Intimação',
            'nomeOrgao': '1ª Vara Federal', 'nomeClasse': 'PROCEDIMENTO COMUM', 'texto': texto,
            'numero_processo': CNJ.replace('-', '').replace('.', ''), 'link': 'https://comunica.pje.jus.br/x',
            'destinatarios': [{'nome': 'Maria Autora', 'polo': 'A'}, {'nome': 'Empresa Ré SA', 'polo': 'P'}], **kw}


def response(items, status=200, count=None):
    return mock.Mock(status_code=status, json=lambda: {'status': 'success', 'count': count if count is not None else len(items), 'items': items})


class ProviderAndTriageTests(APITestCase):
    def test_normaliza_os_dois_formatos(self):
        n = djen.normalize(item())
        self.assertEqual((n['external_id'], n['cnj'], n['disponibilizada_em']), ('1', CNJ, date(2026, 3, 6)))
        self.assertIn('JULGO PROCEDENTE o pedido & condeno', n['texto'])
        self.assertNotIn('<p>', n['texto'])
        self.assertEqual(n['partes'][1], {'nome': 'Empresa Ré SA', 'polo': 'P'})
        alt = djen.normalize({'hash': 'abc', 'datadisponibilizacao': '06/03/2026', 'numeroprocessocommascara': CNJ, 'link': 'javascript:x'})
        self.assertEqual((alt['external_id'], alt['disponibilizada_em'], alt['cnj'], alt['link']), ('abc', date(2026, 3, 6), CNJ, ''))
        self.assertIsNone(djen.normalize({'id': 9}))                              # sem data

    def test_triagem_local(self):
        t = local_triage(djen.clean_text(SENTENCA), 'Intimação')
        self.assertEqual((t['ato'], t['prazo_dias'], t['fatal']), ('Sentença', 15, True))
        self.assertIn('típico', t['prazo_origem'])
        t = local_triage('Intime-se a parte autora para, no prazo de 10 (dez) dias, juntar documentos.')
        self.assertEqual((t['ato'], t['prazo_dias'], t['prazo_origem'], t['confianca']), ('Despacho', 10, 'texto', 80))
        self.assertEqual(local_triage('Manifeste-se no prazo de quinze dias.')['prazo_dias'], 15)
        t = local_triage('Designo audiência de conciliação para o dia 20/04/2026, às 14h30, por videoconferência.')
        self.assertEqual((t['ato'], t['audiencia'], t['prazo_dias']), ('Audiência', '20/04/2026 14:30', None))
        self.assertEqual(local_triage('Ciência às partes.')['prazo_dias'], 5)       # CPC art. 218 §3º

    @mock.patch('publications.providers.djen.requests.get')
    def test_paginacao_e_erros(self, get):
        get.side_effect = [response([item(i) for i in range(1, 101)], count=150), response([item(i) for i in range(101, 151)], count=150)]
        self.assertEqual(len(djen.search('123', 'sp', date(2026, 3, 1), date(2026, 3, 6))), 150)
        self.assertEqual(get.call_args_list[0].kwargs['params']['ufOab'], 'SP')
        get.side_effect = None
        get.return_value = response([], status=429)
        with self.assertRaises(djen.ProviderError) as ctx:
            djen.search('123', 'SP', date(2026, 3, 1), date(2026, 3, 6))
        self.assertTrue(ctx.exception.retryable)
        get.return_value = response([], status=400)
        with self.assertRaises(djen.ProviderError) as ctx:
            djen.search('123', 'SP', date(2026, 3, 1), date(2026, 3, 6))
        self.assertFalse(ctx.exception.retryable)


@mock.patch('publications.triage.ai_triage', return_value=None)
class CaptureTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.viewer = make_user('ver@x.com', self.org, role='VIEWER')
        self.watch = OabWatch.objects.create(organization=self.org, numero='123456', uf='SP', responsavel=self.member)
        self.c = APIClient()
        self.c.force_authenticate(self.member)

    def poll(self, items, **kw):
        with mock.patch('publications.providers.djen.requests.get', return_value=response(items)):
            return services.poll_watch(self.watch, today=date(2026, 3, 6), **kw)

    def test_captura_tria_calcula_vincula_e_nao_duplica(self, _ai):
        case = MonitoredCase.objects.create(organization=self.org, cnj=CNJ, tribunal='trf1')
        with mock.patch('automations.engine.emit') as emit:
            self.assertEqual(self.poll([item(1), item(2, texto='Intime-se para manifestação no prazo de 5 (cinco) dias.')])['new'], 2)
            self.assertEqual(emit.call_count, 2)
            self.assertEqual(emit.call_args.args[1], 'publication_new')
        self.assertEqual(self.poll([item(1)])['new'], 0)
        p = Publication.objects.get(external_id='1')
        self.assertEqual((p.publicada_em, p.vencimento), (date(2026, 3, 9), date(2026, 3, 30)))   # 15 dias úteis a partir de 09/03
        self.assertEqual(p.case, case)
        self.assertEqual(Publication.objects.get(external_id='2').vencimento, date(2026, 3, 16))
        with connection.cursor() as cur:
            cur.execute("SELECT texto, cnj, partes FROM publications_publication WHERE external_id='1'")
            self.assertTrue(all(v.startswith('enc::') for v in cur.fetchone()))
        from notifications.models import Notification
        self.assertTrue(Notification.objects.filter(user=self.member, link='/publicacoes').exists())
        self.assertTrue(AuditEvent.objects.filter(action='publication.captured').exists())

    def test_erro_do_djen_fica_registrado(self, _ai):
        with mock.patch('publications.providers.djen.requests.get', return_value=response([], status=503)):
            res = services.poll_watch(self.watch)
        self.watch.refresh_from_db()
        self.assertIn('503', self.watch.last_error)
        self.assertEqual(res['new'], 0)

    def test_triagem_pela_ia_complementa(self, ai):
        ai.return_value = {'ato': 'Sentença', 'prazo_dias': 15, 'prazo_justificativa': 'CPC art. 1.003 §5º', 'fatal': True,
                           'providencia': 'Apelar.', 'resumo': 'Procedente.', 'audiencia': None, 'origem': 'GROQ'}
        self.poll([item(1)])
        t = Publication.objects.get().triage
        self.assertEqual((t['origem'], t['providencia'], t['prazo_origem'], t['confianca']), ('GROQ', 'Apelar.', 'CPC art. 1.003 §5º', 85))

    def test_api_oabs_permissoes(self, _ai):
        self.assertEqual(self.c.post('/api/v1/publications/oabs/', {'numero': '999', 'uf': 'RJ'}, format='json').status_code, 403)
        self.c.force_authenticate(self.owner)
        res = self.c.post('/api/v1/publications/oabs/', {'numero': '012.345', 'uf': 'rj', 'nome': 'Dra. Ana'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()['numero'], res.json()['uf']), ('12345', 'RJ'))
        self.assertEqual(self.c.post('/api/v1/publications/oabs/', {'numero': '12345', 'uf': 'RJ'}, format='json').status_code, 409)
        self.assertEqual(self.c.post('/api/v1/publications/oabs/', {'numero': '1', 'uf': 'XX'}, format='json').status_code, 400)
        self.assertEqual(len(self.c.get('/api/v1/publications/oabs/').json()), 2)
        wid = res.json()['id']
        self.assertFalse(self.c.patch(f'/api/v1/publications/oabs/{wid}/', {'ativa': False}, format='json').json()['ativa'])
        with mock.patch('publications.providers.djen.requests.get', return_value=response([item(5)])):
            self.c.force_authenticate(self.member)
            self.assertEqual(self.c.post(f'/api/v1/publications/oabs/{wid}/check-now/').json()['new'], 1)
            self.c.force_authenticate(self.viewer)
            self.assertEqual(self.c.post(f'/api/v1/publications/oabs/{wid}/check-now/').status_code, 403)
        self.c.force_authenticate(self.owner)
        self.assertEqual(self.c.delete(f'/api/v1/publications/oabs/{wid}/').status_code, 204)
        self.assertEqual(Publication.objects.count(), 1)                               # a publicação fica na caixa

    def test_confirmar_cria_prazo_e_acompanha(self, _ai):
        self.poll([item(1)])
        pid = Publication.objects.get().pk
        res = self.c.get('/api/v1/publications/')
        self.assertEqual((res.json()['total'], res.json()['contagem']['nova']), (1, 1))
        self.assertNotIn('texto', res.json()['resultados'][0])
        self.assertIn('JULGO PROCEDENTE', self.c.get(f'/api/v1/publications/{pid}/').json()['texto'])
        self.assertEqual(self.c.get(f'/api/v1/publications/{pid}/prazo/', {'dias': 5}).json()['vencimento'], '2026-03-16')
        self.c.force_authenticate(self.viewer)
        self.assertEqual(self.c.post(f'/api/v1/publications/{pid}/confirm/', {}, format='json').status_code, 403)
        self.c.force_authenticate(self.member)
        res = self.c.post(f'/api/v1/publications/{pid}/confirm/', {'prazo_dias': 5, 'acompanhar': True}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()['status'], res.json()['vencimento']), ('confirmada', '2026-03-16'))
        task = UserTask.objects.get()
        self.assertEqual((task.responsavel, task.priority), (self.member, 'alta'))
        self.assertTrue(task.titulo.startswith('Prazo: Sentença'))
        self.assertTrue(MonitoredCase.objects.filter(organization=self.org, tribunal='trf1').exists())
        self.assertEqual(self.c.post(f'/api/v1/publications/{pid}/confirm/', {}, format='json').status_code, 409)
        from brain.models import AIFeedback
        self.assertEqual(AIFeedback.objects.get().decision, 'edited')                    # ajustou o prazo: vira aprendizado
        self.assertEqual(self.c.post(f'/api/v1/publications/{pid}/reopen/').json()['status'], 'nova')
        self.assertEqual(self.c.post(f'/api/v1/publications/{pid}/discard/', {'motivo': 'duplicada'}, format='json').json()['status'],
                         'descartada')
        self.assertEqual(self.c.get('/api/v1/publications/', {'status': 'descartada'}).json()['total'], 1)
        self.assertEqual(self.c.get('/api/v1/publications/', {'cnj': CNJ, 'status': 'todas'}).json()['total'], 1)

    def test_validacao_e_isolamento(self, _ai):
        self.poll([item(1)])
        pid = Publication.objects.get().pk
        self.assertEqual(self.c.post(f'/api/v1/publications/{pid}/confirm/', {'prazo_dias': 0}, format='json').status_code, 400)
        self.assertEqual(self.c.post(f'/api/v1/publications/{pid}/confirm/', {'vencimento': 'amanhã'}, format='json').status_code, 400)
        other = make_user('o@y.com', make_org('Outro'), role='OWNER')
        self.c.force_authenticate(other)
        self.assertEqual(self.c.get(f'/api/v1/publications/{pid}/').status_code, 404)
        self.assertEqual(self.c.get('/api/v1/publications/').json()['total'], 0)

    def test_regra_de_automacao_publicacao_nova(self, _ai):
        self.poll([item(1)])
        pub = Publication.objects.get()
        t = TEMPLATES['publicacao_prazo_fatal']
        rule = Rule.objects.create(organization=self.org, enabled=True, **{**catalog.clean_rule(t), 'name': t['name']})
        with mock.patch('django.utils.timezone.localdate', return_value=date(2026, 3, 9)):
            run = engine.execute(rule.pk, {'publication_id': pub.pk}, 'p1')
        self.assertEqual(run.status, 'success', run.steps)
        task = UserTask.objects.get()
        self.assertEqual(task.scheduled_at.date(), date(2026, 3, 26))                    # 2 dias úteis antes de 30/03
        self.assertEqual(task.responsavel, self.member)
        self.assertIn('Sentença', task.titulo)
