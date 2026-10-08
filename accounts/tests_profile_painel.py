"""CAD-230: foto e capa do perfil que ficam ao recarregar, e painel contado nos dados reais do escritório."""
import io
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from cadrius.tests_security import make_org, make_user

MEDIA = tempfile.mkdtemp(prefix='cadrius-test-media-')


def image_file(name='foto.jpg', fmt='JPEG', size=(900, 700), color=(20, 90, 160)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f'image/{fmt.lower()}')


@override_settings(MEDIA_ROOT=MEDIA, API_PUBLIC_URL='https://api.example.com')
class ProfileImageTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.org = make_org()
        self.user = make_user('dono@x.com', self.org, role='OWNER')
        self.client.force_authenticate(self.user)

    def _get_image(self, url):
        self.client.force_authenticate(None)                 # o link funciona sem login (é assinado)
        resp = self.client.get(url.replace('https://api.example.com', ''))
        self.client.force_authenticate(self.user)
        return resp

    def test_foto_fica_depois_de_recarregar_e_link_muda_ao_trocar(self):
        r = self.client.post('/api/v1/auth/profile/imagem/foto/', {'arquivo': image_file()}, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        url = r.data['profile_picture']
        self.assertTrue(url.startswith('https://api.example.com/api/v1/publico/perfil/'))
        again = self.client.get('/api/v1/auth/user/').data['profile_picture']      # "recarregar a página"
        self.assertEqual(again, url)
        img = self._get_image(url)
        self.assertEqual(img.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(b''.join(img.streaming_content))).size, (512, 512))
        r2 = self.client.post('/api/v1/auth/profile/imagem/foto/', {'arquivo': image_file(color=(200, 0, 0))}, format='multipart')
        self.assertNotEqual(r2.data['profile_picture'], url)
        self.assertEqual(self._get_image(url).status_code, 404)                    # a antiga não fica servida

    def test_capa_com_imagem_fundo_pronto_e_frase(self):
        r = self.client.post('/api/v1/auth/profile/imagem/capa/', {'arquivo': image_file('capa.png', 'PNG', (2400, 900))},
                             format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Image.open(io.BytesIO(b''.join(self._get_image(r.data['cover_image']).streaming_content))).size,
                         (1600, 480))
        r = self.client.patch('/api/v1/auth/profile/', {'cover_preset': 'vinho', 'cover_caption': 'Direito de família'}, format='json')
        self.assertEqual((r.data['cover_preset'], r.data['cover_caption']), ('vinho', 'Direito de família'))
        self.assertEqual(self.client.patch('/api/v1/auth/profile/', {'cover_preset': 'neon'}, format='json').status_code, 400)
        r = self.client.delete('/api/v1/auth/profile/imagem/capa/')
        self.assertIsNone(r.data['cover_image'])

    def test_arquivo_que_nao_e_imagem_e_recusado(self):
        fake = SimpleUploadedFile('x.jpg', b'<?php echo 1; ?>', content_type='image/jpeg')
        r = self.client.post('/api/v1/auth/profile/imagem/foto/', {'arquivo': fake}, format='multipart')
        self.assertEqual(r.status_code, 400)
        gif = io.BytesIO()
        Image.new('RGB', (10, 10)).save(gif, 'GIF')
        r = self.client.post('/api/v1/auth/profile/imagem/foto/',
                             {'arquivo': SimpleUploadedFile('a.gif', gif.getvalue(), content_type='image/gif')}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.post('/api/v1/auth/profile/imagem/outra/', {'arquivo': image_file()},
                                          format='multipart').status_code, 400)

    def test_token_adulterado_nao_serve_nada(self):
        self.assertEqual(self.client.get('/api/v1/publico/perfil/abc/').status_code, 404)


class PainelTests(APITestCase):
    def setUp(self):
        self.org = make_org()
        self.user = make_user('dono@x.com', self.org, role='OWNER')
        self.client.force_authenticate(self.user)

    def test_numeros_vem_dos_dados_do_escritorio(self):
        from automations.models import Rule
        from documents.models import Document
        from tasks.models import UserTask
        Document.objects.create(organization=self.org, nome='contrato.pdf', tipo='contrato', status='pronto')
        Rule.objects.create(organization=self.org, name='Avisar', trigger='task_overdue', enabled=True, actions=[])
        now = timezone.now()
        UserTask.objects.create(titulo='Hoje', scheduled_at=now, responsavel=self.user)
        UserTask.objects.create(titulo='Atrasada', scheduled_at=now - timedelta(days=3), responsavel=self.user)
        UserTask.objects.create(titulo='Feita', scheduled_at=now - timedelta(days=2), responsavel=self.user, completed=True)
        data = self.client.get('/api/v1/dashboard/stats/').data
        self.assertEqual(data['total_documentos'], 1)
        self.assertEqual(data['automacoes_ativas'], 1)
        self.assertEqual(data['tarefas_atrasadas'], 1)
        painel = [t['title'] if 'title' in t else t.get('titulo') for t in self.client.get('/api/v1/tasks/?periodo=painel').data]
        self.assertEqual(len(painel), 2)                          # hoje + atrasada (a feita fica de fora)
        self.assertEqual(len(self.client.get('/api/v1/tasks/').data), 1)   # sem o parâmetro, segue como antes
        late = UserTask.objects.get(titulo='Atrasada')
        r = self.client.patch(f'/api/v1/tasks/{late.pk}/', {'completed': True}, format='json')
        self.assertEqual(r.status_code, 200)                      # concluir a atrasada direto do painel
