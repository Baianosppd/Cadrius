from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from backoffice.tests import staff
from cadrius.tests_security import make_org, make_user
from integrations.models import AppConnection
from marketing import compliance, ideas, services
from marketing.models import ContentPiece


class ComplianceTests(APITestCase):
    def test_regras_da_oab(self):
        bad = ('Somos o melhor escritório da cidade! Garantimos 100% de sucesso. Consulta gratuita, chame no WhatsApp agora. '
               'Meu cliente ganhou R$ 50 mil.')
        rules = {a['regra'] for a in compliance.check(bad, 'escritorio', 'instagram')}
        self.assertTrue({'Promessa de resultado', 'Mercantilização / preço', 'Captação de clientela', 'Autopromoção comparativa',
                         'Menção a cliente ou caso'} <= rules)
        self.assertTrue(compliance.blocking(compliance.check(bad, 'escritorio')))
        ok = 'Você sabia que o consumidor tem 90 dias para reclamar de defeito em produto durável? Saiba mais no nosso site.'
        self.assertEqual(compliance.check(ok, 'escritorio', 'instagram'), [])
        self.assertFalse(compliance.blocking(compliance.check('Especialista em direito de família', 'escritorio')))
        self.assertIn('Dado pessoal (CPF)', {a['regra'] for a in compliance.check('CPF 529.982.247-25', 'escritorio')})
        self.assertIn('Tamanho', {a['regra'] for a in compliance.check('x' * 2300, 'escritorio', 'instagram')})
        self.assertEqual(compliance.check('Garantimos 100% seguro', 'cadrius')[0]['regra'], 'Promessa absoluta')

    def test_ideias(self):
        out = ideas.office_ideas(['consumidor'], today=date(2026, 3, 1))
        self.assertEqual(out['datas'][0]['ocasiao'], 'Dia do Consumidor')
        self.assertTrue(all(t['area'] == 'consumidor' for t in out['temas']))
        self.assertTrue(ideas.office_ideas([], today=date(2026, 3, 1))['temas'])
        self.assertTrue(ideas.cadrius_ideas()['temas'])


class OfficeFlowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.viewer = make_user('ver@x.com', self.org, role='VIEWER')
        self.c = APIClient()
        self.c.force_authenticate(self.member)

    def gen(self, **kw):
        body = {'canal': 'instagram', 'tema': 'Prazo para reclamar de produto com defeito', 'usar_ia': False, **kw}
        return self.c.post('/api/v1/marketing/conteudos/', body, format='json')

    def test_gerar_sem_ia_aprovar_agendar_e_publicar(self):
        res = self.gen()
        self.assertEqual(res.status_code, 201, res.content)
        pid = res.json()['id']
        self.assertIn('[COMPLETAR', res.json()['texto'])
        url = f'/api/v1/marketing/conteudos/{pid}/'
        self.assertEqual(self.c.patch(url, {'status': 'aprovado'}, format='json').status_code, 403)   # advogado não aprova
        self.c.patch(url, {'texto': 'Garantimos o resultado! Consulta grátis.'}, format='json')
        self.c.force_authenticate(self.owner)
        res = self.c.patch(url, {'status': 'aprovado'}, format='json')
        self.assertEqual((res.status_code, res.json()['code']), (409, 'compliance'))
        texto = 'O consumidor tem 90 dias para reclamar de defeito em produto durável (CDC, art. 26). Saiba mais no site.'
        res = self.c.patch(url, {'texto': texto, 'hashtags': ['#direitodoconsumidor', 'cdc'], 'status': 'aprovado'}, format='json')
        self.assertEqual(res.json()['status'], 'aprovado', res.content)
        self.assertIn('#direitodoconsumidor #cdc', res.json()['texto_final'])
        when = (timezone.now() + timedelta(hours=2)).isoformat()
        self.assertEqual(self.c.patch(url, {'agendado_para': when, 'status': 'agendado'}, format='json').status_code, 400)  # IG sem imagem
        res = self.c.patch(url, {'agendado_para': when, 'imagem_url': 'https://img.exemplo.com/a.png', 'status': 'agendado'}, format='json')
        self.assertEqual(res.json()['status'], 'agendado')
        AppConnection.objects.create(user=self.owner, name='Meta', app_name='META',
                                     credentials={'page_id': '1', 'page_access_token': 't', 'ig_user_id': '9'})
        ContentPiece.objects.filter(pk=pid).update(scheduled_at=timezone.now() - timedelta(minutes=1))
        with mock.patch('integrations.services.requests.request') as req:
            req.side_effect = [mock.Mock(status_code=200, json=lambda: {'id': 'c1'}), mock.Mock(status_code=200, json=lambda: {'id': 'ig99'})]
            out = services.publish_due()
        self.assertEqual(out['publicados'], 1)
        piece = ContentPiece.objects.get(pk=pid)
        self.assertEqual((piece.status, piece.external_id), ('publicado', 'ig99'))
        self.assertEqual(req.call_args_list[0].kwargs['data']['image_url'], 'https://img.exemplo.com/a.png')
        self.assertTrue(AuditEvent.objects.filter(action='marketing.content_published').exists())
        from brain.models import AIFeedback, MemoryItem
        self.assertTrue(AIFeedback.objects.filter(action_kind='marketing', decision='edited').exists())
        self.assertTrue(MemoryItem.objects.filter(kind='marketing_example').exists())

    def test_canal_manual_gera_lembrete_e_marcar_publicado(self):
        pid = self.gen(canal='linkedin').json()['id']
        self.c.force_authenticate(self.owner)
        url = f'/api/v1/marketing/conteudos/{pid}/'
        self.c.patch(url, {'texto': 'Texto informativo sobre o tema.', 'status': 'aprovado'}, format='json')
        self.c.patch(url, {'agendado_para': (timezone.now() + timedelta(hours=1)).isoformat(), 'status': 'agendado'}, format='json')
        ContentPiece.objects.filter(pk=pid).update(scheduled_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(services.publish_due()['lembretes'], 1)
        self.assertEqual(services.publish_due()['lembretes'], 0)              # só lembra uma vez
        self.assertEqual(self.c.post(f'{url}publicar/').status_code, 400)       # LinkedIn não publica sozinho
        self.assertEqual(self.c.patch(url, {'status': 'publicado'}, format='json').json()['status'], 'publicado')

    def test_ia_usa_perfil_e_cobra_credito(self):
        from brain.models import OfficeProfile
        OfficeProfile.objects.create(organization=self.org, areas=['consumidor'], tone='didatico', city='Recife')
        fake = {'titulo': 'Defeito em produto', 'texto': 'Texto gerado.', 'hashtags': ['cdc'], 'sugestao_imagem': 'balança'}
        with mock.patch('documents.pipeline.pick_provider', return_value='GROQ'), \
                mock.patch('extraction.ai_wrapper.extract_fields_from_text', return_value=fake) as call, \
                mock.patch('billing.credits.check_credit_available', return_value=(True, '')), \
                mock.patch('billing.credits.consume_credit') as consume:
            res = self.gen(usar_ia=True)
        self.assertEqual((res.json()['ia'], res.json()['texto']), ('GROQ', 'Texto gerado.'))
        prompt = call.call_args.args[2]
        self.assertIn('Provimento 205/2021', prompt)
        self.assertIn('Recife', prompt)
        consume.assert_called_once()

    def test_permissoes_isolamento_verificador_e_ideias(self):
        self.c.force_authenticate(self.viewer)
        self.assertEqual(self.gen().status_code, 403)
        self.c.force_authenticate(self.member)
        pid = self.gen().json()['id']
        self.assertEqual(self.gen(canal='tiktok').status_code, 400)
        res = self.c.post('/api/v1/marketing/verificar/', {'texto': 'Somos o número 1 em causas trabalhistas', 'canal': 'linkedin'}, format='json')
        self.assertTrue(res.json()['bloqueado'])
        self.assertIn('datas', self.c.get('/api/v1/marketing/ideias/').json())
        self.assertEqual(self.c.get('/api/v1/marketing/conteudos/').json()['contagem']['rascunho'], 1)
        camp = self.c.post('/api/v1/marketing/campanhas/', {'nome': 'Mês do consumidor', 'canais': ['instagram', 'x']}, format='json')
        self.assertEqual(camp.json()['canais'], ['instagram'])
        other = APIClient()
        other.force_authenticate(make_user('o@y.com', make_org('Outro'), role='OWNER'))
        self.assertEqual(other.get(f'/api/v1/marketing/conteudos/{pid}/').status_code, 404)
        self.assertEqual(other.get('/api/v1/marketing/conteudos/').json()['resultados'], [])


class CadriusMarketingTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.mkt = staff('mkt@cadrius.ia.br', 'marketing')
        self.ti = staff('ti@cadrius.ia.br', 'ti')

    def client_for(self, user, mfa=True):
        c = APIClient()
        c.force_authenticate(user, token={'amr': 'mfa'} if mfa else {})
        return c

    def test_area_marketing_com_mfa(self):
        self.assertEqual(self.client_for(self.ti).get('/api/v1/backoffice/marketing/conteudos/').status_code, 403)
        self.assertEqual(self.client_for(self.mkt, mfa=False).get('/api/v1/backoffice/marketing/conteudos/').status_code, 403)
        c = self.client_for(self.mkt)
        res = c.post('/api/v1/backoffice/marketing/conteudos/', {'canal': 'linkedin', 'tema': 'Prazos em dias úteis sem erro',
                                                                 'usar_ia': False}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIn('cadrius.ia.br', res.json()['texto'])
        self.assertIsNone(ContentPiece.objects.get().organization)
        make_org('Novo escritório')
        growth = c.get('/api/v1/backoffice/marketing/crescimento/').json()
        self.assertGreaterEqual(growth['cadastros'], 1)
        self.assertTrue(growth['playbook'])
        self.assertTrue(c.get('/api/v1/backoffice/marketing/ideias/').json()['temas'])
        org_user = APIClient()
        org_user.force_authenticate(make_user('d@z.com', make_org('Z'), role='OWNER'))
        self.assertEqual(org_user.get('/api/v1/marketing/conteudos/').json()['resultados'], [])   # conteúdo da Cadrius não vaza
