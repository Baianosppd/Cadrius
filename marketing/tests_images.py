"""CAD-226: imagem real para o conteúdo de marketing (IA de imagem ou arte da marca)."""
import base64
import os
from unittest import mock

from django.core.files.storage import default_storage
from rest_framework.test import APIClient, APITestCase

from cadrius.tests_security import make_org, make_user
from marketing import images
from marketing.models import ContentPiece

PNG = base64.b64encode(b'\x89PNG\r\n\x1a\nfake').decode()
NO_KEYS = {'OPENAI_API_KEY': '', 'GEMINI_API_KEY': ''}


class Resp:
    def __init__(self, data, code=200):
        self._data, self.status_code = data, code

    def json(self):
        return self._data


class MarketingImageTests(APITestCase):
    def setUp(self):
        self.org = make_org('Andrade & Lima')
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        self.piece = ContentPiece.objects.create(organization=self.org, channel='instagram', theme='Direitos do consumidor',
                                                 title='5 direitos do consumidor', image_hint='Pessoa conferindo nota fiscal')
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for p in ContentPiece.objects.exclude(image_file=''):
            if default_storage.exists(p.image_file):
                default_storage.delete(p.image_file)

    def url(self):
        return f'/api/v1/marketing/conteudos/{self.piece.pk}/imagem/'

    def test_sem_ia_de_imagem_faz_arte_da_marca_e_link_publico_funciona(self):
        with mock.patch.dict(os.environ, NO_KEYS):
            res = self.c.post(self.url(), {}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body['imagem_origem'], 'marca')
        self.assertIn('Nenhuma IA de imagem', body['aviso'])
        path = body['imagem_url'].split('testserver')[-1]
        img = APIClient().get(path)                                     # sem login
        self.assertEqual(img.status_code, 200)
        self.assertEqual(img['Content-Type'], 'image/png')
        self.assertTrue(b''.join(img.streaming_content).startswith(b'\x89PNG'))
        self.assertEqual(APIClient().get(path[:-5] + 'xxxx/').status_code, 404)

    def test_openai_gera_imagem_e_cobra_so_quando_entrega(self):
        with mock.patch.dict(os.environ, {**NO_KEYS, 'OPENAI_API_KEY': 'k'}), \
                mock.patch('marketing.images.requests.post', return_value=Resp({'data': [{'b64_json': PNG}]})) as post, \
                mock.patch('billing.credits.charge', return_value=(True, '')) as charge:
            res = self.c.post(self.url(), {'sugestao_imagem': 'Balança da justiça sobre mesa de madeira'}, format='json')
        self.assertEqual(res.json()['imagem_origem'], 'openai')
        prompt = post.call_args.kwargs['json']['prompt']
        self.assertIn('Balança da justiça', prompt)
        self.assertIn('sem texto escrito', prompt)
        charge.assert_called_once()
        self.assertEqual(charge.call_args.args[1], 'marketing_image')

    def test_ia_falha_cai_na_arte_da_marca_sem_cobrar(self):
        with mock.patch.dict(os.environ, {**NO_KEYS, 'OPENAI_API_KEY': 'k', 'GEMINI_API_KEY': 'g'}), \
                mock.patch('marketing.images.requests.post', return_value=Resp({}, 500)), \
                mock.patch('billing.credits.charge') as charge:
            res = self.c.post(self.url(), {}, format='json').json()
        self.assertEqual(res['imagem_origem'], 'marca')
        self.assertIn('não respondeu', res['aviso'])
        charge.assert_not_called()

    def test_gemini_e_politica_do_escritorio(self):
        from aigov.models import AIGovernancePolicy
        policy, _ = AIGovernancePolicy.objects.get_or_create(organization=self.org)
        policy.allowed_providers = ['GEMINI']
        policy.save()
        gem = Resp({'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': 'image/png', 'data': PNG}}]}}]})
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'k', 'GEMINI_API_KEY': 'g'}):
            self.assertEqual(images.providers(self.org), ['GEMINI'])
            with mock.patch('marketing.images.requests.post', return_value=gem), mock.patch('billing.credits.charge', return_value=(True, '')):
                res = self.c.post(self.url(), {}, format='json').json()
        self.assertEqual(res['imagem_origem'], 'gemini')

    def test_editar_mantem_url_gerada(self):
        with mock.patch.dict(os.environ, NO_KEYS):
            url = self.c.post(self.url(), {}, format='json').json()['imagem_url']
        res = self.c.patch(f'/api/v1/marketing/conteudos/{self.piece.pk}/', {'imagem_url': url, 'texto': 'Novo'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
