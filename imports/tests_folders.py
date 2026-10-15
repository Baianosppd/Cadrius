"""CAD-234: carteira de clientes a partir de pastas (Google Drive ou .zip)."""
import io
import os
import tempfile
import zipfile
from unittest import mock

from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from documents.models import ClientDocument, Document
from imports import folders
from imports.models import FolderImport

BASE = '/api/v1/imports/pastas/'
CPF = '529.982.247-25'          # CPF válido de exemplo


def make_zip(files: dict, root='Clientes') -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for path, data in files.items():
            z.writestr(f'{root}/{path}' if root else path, data)
    buf.seek(0)
    buf.name = 'Clientes-20261015.zip'
    return buf


SAMPLE = {
    f'Maria Souza - {CPF}/Procuração.pdf': b'%PDF-1.4 procuracao',
    f'Maria Souza - {CPF}/Processo 123/Petição inicial.docx': b'docx',
    'Construtora Vale Azul/Contrato de honorários.pdf': b'%PDF contrato',
    'Construtora Vale Azul/.DS_Store': b'x',
    'Construtora Vale Azul/programa.exe': b'MZ',
    '02 - José Lima/RG.jpg': b'\xff\xd8\xff',
    'leia-me.txt': b'solto na raiz',
}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='cad234-media-'))
class FolderImportTests(APITestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        self.existing = Contact.objects.create(organization=self.org, name='Construtora Vale Azul', kind='cliente')

    def _upload(self, files=SAMPLE, root='Clientes'):
        return self.c.post(f'{BASE}zip/', {'arquivo': make_zip(files, root)}, format='multipart')

    def _run(self, job_id, body=None):
        with mock.patch('core.queue.enqueue') as enq:
            with self.captureOnCommitCallbacks(execute=True):
                res = self.c.post(f'{BASE}{job_id}/importar/', body or {}, format='json')
        self.assertEqual(res.status_code, 202, res.data)
        enq.assert_called_once_with('imports.folders.run', job_id)
        folders.run(job_id)
        return FolderImport.objects.get(pk=job_id)

    def test_nome_da_pasta_vira_nome_e_cpf(self):
        self.assertEqual(folders.parse_folder_name(f'Maria Souza - {CPF}'), ('Maria Souza', '52998224725'))
        self.assertEqual(folders.parse_folder_name('02 - José Lima'), ('José Lima', ''))
        self.assertEqual(folders.parse_folder_name('Cliente 123.456.789-00')[1], '')        # CPF inválido não vira documento

    def test_previa_do_zip_desce_a_pasta_mae_e_ignora_lixo(self):
        res = self._upload()
        self.assertEqual(res.status_code, 201, res.data)
        prev = res.data['previa']
        nomes = [c['nome'] for c in prev['clientes']]
        self.assertEqual(nomes, ['Construtora Vale Azul', 'José Lima', 'Maria Souza'])
        vale = prev['clientes'][0]
        self.assertEqual(vale['contato_existente']['id'], self.existing.pk)
        self.assertEqual((vale['arquivos'], vale['ignorados']), (1, 2))
        maria = prev['clientes'][2]
        self.assertEqual(maria['documento'], CPF)
        self.assertIsNone(maria['contato_existente'])
        self.assertEqual(maria['arquivos'], 2)
        self.assertEqual(res.data['progresso']['soltos'], 1)          # leia-me.txt solto dentro da pasta-mãe
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 1)  # prévia não grava nada
        job = FolderImport.objects.get(pk=res.data['id'])
        self.assertTrue(os.path.exists(job.archive_path))
        self.assertEqual(oct(os.stat(job.archive_path).st_mode & 0o777), '0o600')

    def test_importa_contatos_e_documentos_e_reimportar_nao_duplica(self):
        res = self._upload()
        job = self._run(res.data['id'])
        self.assertEqual(job.status, 'done', job.progress)
        self.assertEqual(job.progress['contatos_novos'], 2)
        self.assertEqual(job.progress['contatos_existentes'], 1)
        self.assertEqual(job.progress['documentos'], 4)
        self.assertEqual(job.archive_path, '')
        self.assertEqual(job.plan, [])
        maria = Contact.objects.get(organization=self.org, document_bidx__isnull=False)
        self.assertEqual(maria.name, 'Maria Souza')
        self.assertEqual(maria.source, 'import')
        docs = Document.objects.filter(contact=maria).order_by('nome')
        self.assertEqual([d.nome for d in docs], ['Processo 123/Petição inicial.docx', 'Procuração.pdf'])
        self.assertEqual(docs[1].tipo, 'procuracao')
        self.assertEqual(docs[0].tipo, 'peticao')
        self.assertEqual(docs[1].arquivo.read(), b'%PDF-1.4 procuracao')     # cifrado em repouso, decifra na leitura
        self.assertTrue(ClientDocument.objects.filter(documento=docs[1]).exists())
        self.assertEqual(Document.objects.filter(contact=self.existing).count(), 1)
        # a lista de documentos filtra pelo contato
        r = self.c.get(f'/api/v1/documentos/?contato={maria.pk}')
        self.assertEqual(r.data['count'], 2)
        # reimportar a mesma pasta: nada duplicado
        job2 = self._run(self._upload().data['id'])
        self.assertEqual(job2.progress['contatos_novos'], 0)
        self.assertEqual(job2.progress['documentos'], 0)
        self.assertEqual(job2.progress['repetidos'], 4)
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 3)

    def test_so_as_pastas_marcadas_e_leitura_com_ia_opcional(self):
        res = self._upload()
        with mock.patch('documents.pipeline.enqueue_processing') as proc:
            job = self._run(res.data['id'], {'selecionadas': [2], 'ler_com_ia': True})
        self.assertEqual(job.progress['documentos'], 2)
        self.assertEqual(proc.call_count, 2)
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 2)

    def test_importacao_grande_continua_em_etapas_sem_duplicar(self):
        res = self._upload()
        with mock.patch('core.queue.enqueue'), self.captureOnCommitCallbacks(execute=True):
            self.c.post(f'{BASE}{res.data["id"]}/importar/', {}, format='json')
        clock = iter(range(0, 10000, 30))                   # cada leitura do relógio avança 30 s: pausa a cada arquivo
        with mock.patch('time.monotonic', side_effect=lambda: next(clock)), mock.patch('core.queue.enqueue') as again:
            for _ in range(20):
                folders.run(res.data['id'])
                if FolderImport.objects.get(pk=res.data['id']).status == 'done':
                    break
        job = FolderImport.objects.get(pk=res.data['id'])
        self.assertEqual(job.status, 'done', job.progress)
        self.assertGreater(again.call_count, 1)
        self.assertEqual((job.progress['contatos_novos'], job.progress['contatos_existentes']), (2, 1))
        self.assertEqual((job.progress['documentos'], job.progress['repetidos']), (4, 0))
        self.assertEqual(Document.objects.filter(organization=self.org).count(), 4)

    def test_zip_invalido_e_sem_pastas(self):
        bad = io.BytesIO(b'nao e zip')
        bad.name = 'x.zip'
        self.assertEqual(self.c.post(f'{BASE}zip/', {'arquivo': bad}, format='multipart').status_code, 400)
        res = self._upload({'solto.pdf': b'x'}, root='')
        self.assertEqual(res.status_code, 400)
        self.assertIn('pastas de clientes', res.data['detail'])

    def test_cancelar_apaga_o_zip_e_outro_escritorio_nao_ve(self):
        res = self._upload()
        job = FolderImport.objects.get(pk=res.data['id'])
        other = APIClient()
        other.force_authenticate(make_user('x@y.com', make_org('Outro'), role='OWNER'))
        self.assertEqual(other.get(f'{BASE}{job.pk}/').status_code, 404)
        self.assertEqual(self.c.delete(f'{BASE}{job.pk}/').status_code, 204)
        self.assertFalse(os.path.exists(job.archive_path))
        job.refresh_from_db()
        self.assertEqual(job.status, 'canceled')

    def test_link_do_drive(self):
        self.assertEqual(folders.drive_folder_id('https://drive.google.com/drive/folders/1AbCdEfGhIjKlMn?usp=sharing'), '1AbCdEfGhIjKlMn')
        with self.assertRaises(folders.FolderImportError):
            folders.drive_folder_id('https://exemplo.com')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='cad234-drive-'))
class DriveFolderImportTests(APITestCase):
    def setUp(self):
        from gcal.models import GoogleCalendarApp, GoogleCalendarLink
        from gcal.platform import DRIVE_READONLY
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        app = GoogleCalendarApp.objects.create(organization=self.org, client_id='c', client_secret='s')
        self.link = GoogleCalendarLink.objects.create(user=self.owner, app=app, refresh_token='r', status='active',
                                                      scopes=f'openid {DRIVE_READONLY}')

    TREE = {
        'root': [{'id': 'f1', 'name': 'Ana Paula', 'mimeType': folders.FOLDER_MIME},
                 {'id': 'x', 'name': 'planilha geral.xlsx', 'mimeType': 'application/vnd.ms-excel', 'size': '10'}],
        'f1': [{'id': 'a', 'name': 'Contrato.pdf', 'mimeType': 'application/pdf', 'size': '12'},
               {'id': 'b', 'name': 'Resumo do caso', 'mimeType': 'application/vnd.google-apps.document'},
               {'id': 'c', 'name': 'Formulário', 'mimeType': 'application/vnd.google-apps.form'}],
    }

    def _fake_call(self, link, method, url, params=None, **kw):
        if url.endswith('/files/root'):
            return {'id': 'root', 'name': 'Clientes do escritório', 'mimeType': folders.FOLDER_MIME}
        parent = params['q'].split("'")[1]
        return {'files': self.TREE.get(parent, [])}

    def test_sem_autorizacao_pede_a_leitura_do_drive(self):
        self.link.scopes = 'openid'
        self.link.save()
        res = self.c.post(BASE, {'link': 'https://drive.google.com/drive/folders/rootrootroot'}, format='json')
        self.assertEqual(res.data['code'], 'drive_auth')
        state = self.c.get(BASE).data['drive']
        self.assertEqual((state['google_conectado'], state['leitura_autorizada']), (True, False))

    def test_lista_e_importa_do_drive_exportando_google_docs(self):
        with mock.patch('gcal.workspace._call', side_effect=self._fake_call), \
                mock.patch('imports.folders.drive_folder_id', return_value='root'):
            res = self.c.post(BASE, {'link': 'https://drive.google.com/drive/folders/qualquer'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['nome'], 'Clientes do escritório')
        ana = res.data['previa']['clientes'][0]
        self.assertEqual((ana['nome'], ana['arquivos']), ('Ana Paula', 2))
        self.assertEqual(ana['exemplos'], ['Contrato.pdf', 'Resumo do caso.pdf'])
        calls = []

        def fake_download(token, url, params=None, max_bytes=0):
            calls.append((url, params))
            return b'%PDF conteudo'
        with self.captureOnCommitCallbacks(execute=True), mock.patch('core.queue.enqueue'):
            self.c.post(f'{BASE}{res.data["id"]}/importar/', {}, format='json')
        with mock.patch('gcal.google_api.download', side_effect=fake_download), \
                mock.patch('gcal.sync._access_token', return_value='at'):
            folders.run(res.data['id'])
        job = FolderImport.objects.get(pk=res.data['id'])
        self.assertEqual(job.status, 'done', job.progress)
        self.assertEqual(job.progress['documentos'], 2)
        self.assertTrue(any(u.endswith('/files/b/export') and p['mimeType'] == 'application/pdf' for u, p in calls))
        self.assertTrue(any(u.endswith('/files/a') and p['alt'] == 'media' for u, p in calls))

    def test_conectar_pede_o_escopo_extra_e_volta_para_importar(self):
        from gcal.platform import DRIVE_READONLY
        res = self.c.post('/api/v1/integrations/google-calendar/connect/', {'acesso': 'drive_leitura', 'volta': 'importar'},
                          format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn('drive.readonly', res.data['authorization_url'])
        self.assertIn(DRIVE_READONLY.split('/')[-1], res.data['authorization_url'])
