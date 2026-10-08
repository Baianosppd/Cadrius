"""CAD-226/231: imagem e vídeo do marketing — artes prontas e fotos (todos os planos), Gemini com o adicional de mídia."""
import base64
import io
import os
from datetime import timedelta
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from billing import addons
from billing.models import MediaAddon, SubscriptionPlan
from billing.stripe_sync import apply_event
from cadrius.tests_security import make_org, make_user
from marketing import images, media
from marketing.models import ContentPiece, MarketingAsset

NO_KEYS = {'OPENAI_API_KEY': '', 'GEMINI_API_KEY': ''}
GEM = {**NO_KEYS, 'GEMINI_API_KEY': 'g'}


def png_bytes(color=(200, 30, 30), size=(64, 48), fmt='PNG'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, fmt)
    return buf.getvalue()


PNG = base64.b64encode(png_bytes()).decode()


class Resp:
    def __init__(self, data, code=200, content=b''):
        self._data, self.status_code, self.content = data, code, content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        yield self.content


def gemini_ok():
    return Resp({'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': 'image/png', 'data': PNG}}]}}]})


class Base(APITestCase):
    def setUp(self):
        self.org = make_org('Andrade & Lima')
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        self.piece = ContentPiece.objects.create(organization=self.org, channel='instagram', theme='Direitos do consumidor',
                                                 title='5 direitos do consumidor', image_hint='Pessoa conferindo nota fiscal')
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for p in ContentPiece.objects.all():
            for f in (p.image_file, p.video_file):
                if f and default_storage.exists(f):
                    default_storage.delete(f)
        for a in MarketingAsset.objects.all():
            if default_storage.exists(a.file):
                default_storage.delete(a.file)

    def url(self, extra='imagem/'):
        return f'/api/v1/marketing/conteudos/{self.piece.pk}/{extra}'

    def upload(self, data=None, name='fachada.jpg'):
        f = SimpleUploadedFile(name, data or png_bytes(fmt='JPEG'), content_type='image/jpeg')
        return self.c.post('/api/v1/marketing/fotos/', {'arquivo': f}, format='multipart')


class BrandArtTests(Base):
    def test_arte_pronta_sem_adicional_e_link_publico(self):
        with mock.patch.dict(os.environ, NO_KEYS):
            res = self.c.post(self.url(), {'modo': 'marca', 'estilo': 'dica'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body['imagem_origem'], 'marca')
        path = body['imagem_url'].split('testserver')[-1]
        img = APIClient().get(path)                                     # sem login
        self.assertEqual(img.status_code, 200)
        self.assertTrue(b''.join(img.streaming_content).startswith(b'\x89PNG'))
        self.assertEqual(APIClient().get(path[:-5] + 'xxxx/').status_code, 404)

    def test_todos_os_estilos_com_logo_e_foto(self):
        logo = png_bytes((10, 10, 10), (300, 100))
        for style in images.STYLES:
            out = images.brand_card('Prazo para recorrer de multa de trânsito: o que saber antes de assinar', 'Andrade & Lima',
                                    '#7c2d12', style=style, photo=png_bytes(size=(800, 600)), logo=logo)
            from PIL import Image
            self.assertEqual(Image.open(io.BytesIO(out)).size, (1080, 1080), style)

    def test_foto_do_escritorio_como_fundo_e_como_imagem(self):
        asset = self.upload().json()
        res = self.c.post(self.url(), {'modo': 'marca', 'estilo': 'foto', 'foto_id': asset['id']}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        res = self.c.post(self.url(), {'modo': 'foto', 'foto_id': asset['id']}, format='json')
        self.assertEqual(res.json()['imagem_origem'], 'foto')
        other = make_org('Outro')
        alien = MarketingAsset.objects.create(organization=other, file='marketing/fotos/x.jpg')
        self.assertEqual(self.c.post(self.url(), {'modo': 'foto', 'foto_id': alien.pk}, format='json').status_code, 400)


class AssetTests(Base):
    def test_upload_limpa_exif_lista_e_apaga(self):
        res = self.upload()
        self.assertEqual(res.status_code, 201, res.content)
        a = MarketingAsset.objects.get(pk=res.json()['id'])
        self.assertTrue(a.file.startswith('marketing/fotos/'))
        got = APIClient().get(res.json()['url'].split('testserver')[-1])
        self.assertEqual((got.status_code, got['Content-Type']), (200, 'image/jpeg'))
        self.assertEqual(len(self.c.get('/api/v1/marketing/fotos/').json()), 1)
        self.assertEqual(self.c.delete(f'/api/v1/marketing/fotos/{a.pk}/').status_code, 204)
        self.assertFalse(default_storage.exists(a.file))

    def test_recusa_o_que_nao_e_imagem(self):
        res = self.upload(b'<script>alert(1)</script>', 'x.jpg')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(MarketingAsset.objects.count(), 0)

    def test_link_assinado_nao_serve_fora_do_marketing(self):
        from django.core import signing
        token = signing.dumps({'f': 'accounts/../segredo.txt'}, salt=media.SALT, compress=True)
        self.assertEqual(APIClient().get(f'/api/v1/publico/marketing/arquivo/{token}/').status_code, 404)


class MediaAddonGateTests(Base):
    def test_ia_sem_adicional_pede_o_adicional(self):
        with mock.patch.dict(os.environ, GEM), mock.patch('marketing.images.requests.post') as post:
            res = self.c.post(self.url(), {'modo': 'ia'}, format='json')
            vid = self.c.post(self.url('video/'), {}, format='json')
        self.assertEqual((res.status_code, res.json()['code']), (402, 'addon_required'))
        self.assertEqual(vid.status_code, 402)
        post.assert_not_called()

    def test_enterprise_inclui_e_cortesia_vence(self):
        self.assertFalse(addons.media_ai_enabled(self.org))
        addons.activate(self.org, source='cortesia', ends_at=timezone.now() + timedelta(days=1))
        self.assertTrue(addons.media_ai_enabled(self.org))
        self.assertFalse(addons.media_ai_enabled(self.org, now=timezone.now() + timedelta(days=2)))
        MediaAddon.objects.all().delete()
        ent, _ = SubscriptionPlan.objects.get_or_create(tier='ENTERPRISE', defaults=dict(name='Enterprise', price_brl=999))
        self.org.plan = ent
        self.org.save()
        st = addons.status(self.org)
        self.assertTrue(st['ativo'] and st['incluido_no_plano'])
        self.assertFalse(st['pode_contratar'])

    def test_gemini_com_fotos_de_referencia_cobra_ao_entregar(self):
        addons.activate(self.org, source='cortesia')
        ref = self.upload().json()['id']
        with mock.patch.dict(os.environ, GEM), \
                mock.patch('marketing.images.requests.post', return_value=gemini_ok()) as post, \
                mock.patch('billing.credits.charge', return_value=(True, '')) as charge:
            res = self.c.post(self.url(), {'modo': 'ia', 'referencias': [ref], 'sugestao_imagem': 'Fachada do escritório'},
                              format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['imagem_origem'], 'gemini')
        parts = post.call_args.kwargs['json']['contents'][0]['parts']
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0]['inlineData']['mimeType'], 'image/jpeg')
        self.assertIn('referência fiel', parts[1]['text'])
        self.assertIn('Fachada do escritório', parts[1]['text'])
        self.assertIn('generativelanguage.googleapis.com', post.call_args.args[0])
        self.assertEqual(charge.call_args.args[1], 'marketing_image')

    def test_falha_do_gemini_nao_cobra_e_avisa(self):
        addons.activate(self.org, source='cortesia')
        with mock.patch.dict(os.environ, GEM), mock.patch('marketing.images.requests.post', return_value=Resp({}, 500)), \
                mock.patch('billing.credits.charge') as charge:
            res = self.c.post(self.url(), {'modo': 'ia'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('não respondeu', res.json()['detail'])
        charge.assert_not_called()

    def test_politica_sem_gemini_bloqueia(self):
        from aigov.models import AIGovernancePolicy
        addons.activate(self.org, source='cortesia')
        policy, _ = AIGovernancePolicy.objects.get_or_create(organization=self.org)
        policy.allowed_providers = ['OPENAI']
        policy.save()
        with mock.patch.dict(os.environ, GEM):
            self.assertEqual(images.providers(self.org), [])

    def test_editar_mantem_url_gerada(self):
        url = self.c.post(self.url(), {'modo': 'marca'}, format='json').json()['imagem_url']
        res = self.c.patch(f'/api/v1/marketing/conteudos/{self.piece.pk}/', {'imagem_url': url, 'texto': 'Novo'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)


class VideoTests(Base):
    def setUp(self):
        super().setUp()
        addons.activate(self.org, source='cortesia')

    def test_pede_consulta_baixa_e_cobra_uma_vez(self):
        asset = self.upload().json()['id']
        op = 'models/veo-3.1-fast-generate-preview/operations/abc'
        with mock.patch.dict(os.environ, GEM), mock.patch('marketing.media.requests.post', return_value=Resp({'name': op})) as post:
            res = self.c.post(self.url('video/'), {'sugestao': 'Advogada explicando em escritório claro', 'foto_id': asset},
                              format='json')
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(res.json()['video_status'], 'gerando')
        body = post.call_args.kwargs['json']
        self.assertEqual(body['parameters']['aspectRatio'], '9:16')
        self.assertIn('bytesBase64Encoded', body['instances'][0]['image'])
        self.assertIn(':predictLongRunning', post.call_args.args[0])
        with mock.patch.dict(os.environ, GEM):                     # segundo pedido enquanto gera
            self.assertEqual(self.c.post(self.url('video/'), {}, format='json').status_code, 400)

        pending = Resp({'done': False})
        done = Resp({'done': True, 'response': {'generateVideoResponse': {'generatedSamples': [
            {'video': {'uri': 'https://generativelanguage.googleapis.com/v1beta/files/x:download'}}]}}})
        mp4 = Resp({}, content=b'\x00\x00\x00\x18ftypmp42')
        with mock.patch.dict(os.environ, GEM), mock.patch('marketing.media.requests.get', side_effect=[pending, done, mp4]), \
                mock.patch('billing.credits.charge', return_value=(True, '')) as charge:
            self.assertEqual(self.c.get(self.url('video/')).json()['video_status'], 'gerando')
            got = self.c.get(self.url('video/')).json()
            again = self.c.get(self.url('video/')).json()            # já pronto: não consulta nem cobra de novo
        self.assertEqual(got['video_status'], 'pronto')
        self.assertEqual(again['video_status'], 'pronto')
        charge.assert_called_once()
        self.assertEqual(charge.call_args.args[1], 'marketing_video')
        file = APIClient().get(got['video_url'].split('testserver')[-1])
        self.assertEqual((file.status_code, file['Content-Type']), (200, 'video/mp4'))

    def test_recusa_do_google_marca_falha_sem_cobrar(self):
        self.piece.video_status, self.piece.video_op = 'gerando', 'models/veo/operations/z'
        self.piece.video_started_at = timezone.now()
        self.piece.save()
        with mock.patch.dict(os.environ, GEM), mock.patch('marketing.media.requests.get',
                                                          return_value=Resp({'done': True, 'error': {'code': 3}})), \
                mock.patch('billing.credits.charge') as charge:
            got = self.c.get(self.url('video/')).json()
        self.assertEqual(got['video_status'], 'falhou')
        self.assertIn('regras de conteúdo', got['video_erro'])
        charge.assert_not_called()


@override_settings(MEDIA_ADDON_PRICE_BRL='149.00', STRIPE_SECRET_KEY='sk_test_x', FRONTEND_URL='https://app.x')
class AddonBillingTests(Base):
    def setUp(self):
        super().setUp()
        plan = SubscriptionPlan.objects.create(name='Pro', tier='PRO', price_brl=299, max_users=5, max_ai_extractions=1500)
        self.org.plan, self.org.subscription_status = plan, 'active'
        self.org.save()

    def event(self, **over):
        base = {'id': 'cs_addon', 'client_reference_id': str(self.org.pk), 'payment_status': 'paid', 'amount_total': 14900,
                'subscription': 'sub_addon', 'metadata': {'kind': 'media_addon'}}
        base.update(over)
        return {'type': 'checkout.session.completed', 'data': {'object': base}}

    def test_status_e_checkout(self):
        st = self.c.get('/api/billing/addons/midia/').json()
        self.assertEqual((st['ativo'], st['pode_contratar'], st['pode_gerenciar'], st['preco']), (False, True, True, '149.00'))
        with mock.patch('billing.views.stripe.checkout.Session.create', return_value=mock.Mock(url='https://stripe/x')) as create:
            res = self.c.post('/api/billing/addons/midia/checkout/', {}, format='json')
        self.assertEqual(res.json()['checkout_url'], 'https://stripe/x')
        kw = create.call_args.kwargs
        self.assertEqual((kw['mode'], kw['metadata']['kind'], kw['line_items'][0]['price_data']['unit_amount']),
                         ('subscription', 'media_addon', 14900))
        member = make_user('adv@x.com', self.org, role='MEMBER')
        c = APIClient()
        c.force_authenticate(member)
        self.assertEqual(c.post('/api/billing/addons/midia/checkout/', {}, format='json').status_code, 403)

    def test_webhook_ativa_so_com_valor_certo_e_cancelamento_nao_mexe_no_plano(self):
        self.assertEqual(apply_event(self.event(amount_total=100)), 'ignored:addon_mismatch')
        self.assertFalse(addons.media_ai_enabled(self.org))
        self.assertEqual(apply_event(self.event()), 'addon_active')
        self.assertTrue(addons.media_ai_enabled(self.org))
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan.tier, 'PRO')                     # o plano não muda
        inv = {'type': 'invoice.payment_succeeded', 'data': {'object': {'id': 'in_1', 'subscription': 'sub_addon', 'amount_paid': 14900}}}
        self.assertEqual(apply_event(inv), 'addon_renewed')
        deleted = {'type': 'customer.subscription.deleted', 'data': {'object': {'id': 'sub_addon'}}}
        self.assertEqual(apply_event(deleted), 'addon_canceled')
        self.assertFalse(addons.media_ai_enabled(self.org))
        self.org.refresh_from_db()
        self.assertEqual(self.org.subscription_status, 'active')
