import io
import zipfile
from datetime import timedelta
from io import StringIO

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from imports import readers, targets
from imports.models import ImportJob

CSV = ('Nome;CPF;E-mail;Celular;Etiquetas;Aceita WhatsApp\n'
       'Maria Souza;529.982.247-25;maria@x.com;(11) 98888-7777;vip;sim\n'
       'João Lima;;joao@x.com;;;não\n'
       'Sem Documento Válido;123;;;;\n'
       'Maria Repetida;52998224725;;;;\n').encode('utf-8')


def xlsx(rows):
    """XLSX mínimo (strings inline) para testar o leitor sem dependências."""
    def cell(ref, v):
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    sheet = ''.join(f'<row r="{i}">' + ''.join(cell(f'{chr(65 + j)}{i}', v) for j, v in enumerate(r)) + '</row>' for i, r in enumerate(rows, 1))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{sheet}</sheetData></worksheet>')
    return buf.getvalue()


class ReaderTests(SimpleTestCase):
    def test_csv_com_ponto_e_virgula_e_acentos(self):
        header, rows = readers.read_file('c.csv', CSV)
        self.assertEqual(header[0], 'Nome')
        self.assertEqual(len(rows), 4)
        header, rows = readers.read_file('c.csv', 'nome,email\nAna,a@x.com\n'.encode('cp1252'))
        self.assertEqual(rows, [['Ana', 'a@x.com']])

    def test_xlsx_e_limites(self):
        header, rows = readers.read_file('p.xlsx', xlsx([['Nome', 'Processo'], ['Ana', '0000832-35.2018.4.01.3202']]))
        self.assertEqual((header, rows), (['Nome', 'Processo'], [['Ana', '0000832-35.2018.4.01.3202']]))
        for name, data in (('a.pdf', b'x'), ('a.csv', b'x' * 2_000_001), ('a.xlsx', b'nao zip'), ('a.csv', b'nome\n')):
            with self.assertRaises(readers.ReadError, msg=name):
                readers.read_file(name, data)

    def test_sugestao_de_colunas(self):
        cols = ['Nome', 'CPF', 'E-mail', 'Celular', 'Etiquetas', 'Aceita WhatsApp']
        self.assertEqual(targets.suggest_mapping('contacts', cols),
                         {'0': 'name', '1': 'document', '2': 'email', '3': 'phone', '4': 'tags', '5': 'whatsapp_consent'})
        self.assertEqual(targets.suggest_mapping('cases', ['Número do processo', 'Cliente']), {'0': 'cnj', '1': 'label'})
        self.assertIn('Falta mapear: Nome.', targets.validate_mapping('contacts', {'1': 'document'})[0])


class ImportFlowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.user = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def upload(self, data=CSV, name='clientes.csv', target='contacts'):
        return self.c.post('/api/v1/imports/', {'file': SimpleUploadedFile(name, data), 'target': target}, format='multipart')

    def test_fluxo_completo_simula_sem_gravar_e_importa(self):
        Contact.objects.create(organization=self.org, name='João Antigo', email='joao@x.com', tags=['antigo'])
        job = self.upload().json()
        self.assertEqual((job['rows_total'], job['mapping']['0']), (4, 'name'))
        commit_url = f"/api/v1/imports/{job['id']}/commit/"
        self.assertEqual(self.c.post(commit_url).status_code, 409)                 # precisa simular antes
        prev = self.c.post(f"/api/v1/imports/{job['id']}/preview/", {'mapping': job['mapping']}, format='json').json()
        self.assertEqual(prev['counts'], {'create': 1, 'update': 1, 'errors': 2})
        self.assertEqual(Contact.objects.count(), 1)                               # simulação não grava
        self.assertEqual([e['row'] for e in prev['errors']], [4, 5])
        done = self.c.post(commit_url).json()
        self.assertEqual(done['summary'], {'created': 1, 'updated': 1, 'skipped': 0, 'errors': 2})
        maria = next(c for c in Contact.objects.all() if c.name == 'Maria Souza')
        self.assertTrue(maria.whatsapp_consent)
        self.assertIn('clientes.csv', maria.consent_source)
        joao = next(c for c in Contact.objects.all() if c.email == 'joao@x.com')
        self.assertEqual(joao.name, 'João Lima')                                   # atualizou pelo e-mail
        self.assertEqual(joao.tags, ['antigo'])
        self.assertEqual(ImportJob.objects.get().rows, [])                         # conteúdo não fica guardado
        self.assertTrue(AuditEvent.objects.filter(action='data.import').exists())

    def test_importa_processos(self):
        job = self.upload(xlsx([['Número do processo', 'Cliente'], ['0000832-35.2018.4.01.3202', 'Ana'], ['123', 'X']]),
                          name='processos.xlsx', target='cases').json()
        self.c.post(f"/api/v1/imports/{job['id']}/preview/", {'mapping': job['mapping']}, format='json')
        done = self.c.post(f"/api/v1/imports/{job['id']}/commit/").json()
        self.assertEqual((done['summary']['created'], done['summary']['errors']), (1, 1))

    def test_permissoes_isolamento_e_limpeza(self):
        viewer = APIClient()
        viewer.force_authenticate(make_user('v@x.com', self.org, role='VIEWER'))
        self.assertEqual(viewer.post('/api/v1/imports/', {}, format='multipart').status_code, 403)
        job = self.upload().json()
        other = APIClient()
        other.force_authenticate(make_user('o@o.com', make_org(), role='OWNER'))
        self.assertEqual(other.get(f"/api/v1/imports/{job['id']}/").status_code, 404)
        ImportJob.objects.filter(pk=job['id']).update(created_at=timezone.now() - timedelta(days=8))
        call_command('purge_import_rows', stdout=StringIO())
        j = ImportJob.objects.get(pk=job['id'])
        self.assertEqual((j.status, j.rows), ('canceled', []))
