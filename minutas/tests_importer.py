"""CAD-231: importar modelos de minuta do escritório (Word, PDF, texto) com os campos reconhecidos."""
import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient, APITestCase

from cadrius.tests_security import make_org, make_user
from minutas import importer, services
from minutas.models import DraftTemplate


def docx(paragraphs):
    body = ''.join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', f'<?xml version="1.0"?><w:document><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


class ImporterTests(APITestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def test_campos_reconhecidos_e_proprios(self):
        body, fields = importer.detect_fields(
            'EXCELENTÍSSIMO JUIZ DA [VARA]\nProcesso nº «número do processo»\n<<CLIENTE>>, contra {RÉU}, valor de [VALOR DA CAUSA].\n'
            'Ver [...] e nota [1]. Assina: ________ OAB {{advogado.oab}}')
        self.assertIn('{{processo.orgao}}', body)
        self.assertIn('{{processo.cnj}}', body)
        self.assertIn('{{cliente.nome}}', body)
        self.assertIn('{{parte_contraria.nome}}', body)
        self.assertIn('{{campo.valor_da_causa}}', body)
        self.assertIn('[...]', body)                          # reticências e notas ficam como estão
        self.assertIn('[1]', body)
        self.assertIn('[COMPLETAR]', body)
        self.assertIn('{{advogado.oab}}', body)
        proprio = next(f for f in fields if f['chave'] == 'campo.valor_da_causa')
        self.assertFalse(proprio['conhecido'])
        rendered = services.render(body, {'cliente.nome': 'Maria'})
        self.assertIn('Maria', rendered)
        self.assertIn('[COMPLETAR: Valor da causa]', rendered)

    def test_previa_e_salvar_word(self):
        raw = docx(['PROCURAÇÃO', 'Outorgante: [NOME DO CLIENTE], residente em [ENDEREÇO].', 'Cidade, [DATA].'])
        up = SimpleUploadedFile('Procuracao_padrao.docx', raw)
        r = self.c.post('/api/v1/minutas/modelos/importar/', {'arquivo': up}, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['tipo'], 'procuracao')
        self.assertEqual(r.data['nome'], 'Procuracao padrao')
        self.assertIn('{{cliente.nome}}', r.data['corpo'])
        self.assertIn('{{hoje}}', r.data['corpo'])
        self.assertEqual(DraftTemplate.objects.count(), 0)                    # prévia não grava
        up = SimpleUploadedFile('Procuracao_padrao.docx', raw)
        r = self.c.post('/api/v1/minutas/modelos/importar/', {'arquivo': up, 'salvar': '1', 'nome': 'Procuração geral'},
                        format='multipart')
        self.assertEqual(r.status_code, 201)
        self.assertIn('campo.endereco', r.data['campos'])
        lista = self.c.get('/api/v1/minutas/modelos/').data['modelos']
        self.assertEqual(lista[0]['nome'], 'Procuração geral')                # aparece para gerar minutas de novo

    def test_texto_e_recusas(self):
        r = self.c.post('/api/v1/minutas/modelos/importar/', {'arquivo': SimpleUploadedFile('m.txt', 'Prezado [cliente], segue.'.encode())},
                        format='multipart')
        self.assertEqual(r.data['tipo'], 'comunicado')
        for name, raw in (('x.exe', b'MZ'), ('x.docx', b'not a zip'), ('x.txt', b'oi')):
            self.assertEqual(self.c.post('/api/v1/minutas/modelos/importar/', {'arquivo': SimpleUploadedFile(name, raw)},
                                         format='multipart').status_code, 400, name)
        other = APIClient()
        other.force_authenticate(self.member)
        self.assertEqual(other.post('/api/v1/minutas/modelos/importar/', {'arquivo': SimpleUploadedFile('m.txt', b'Texto do modelo ok')},
                                    format='multipart').status_code, 403)
