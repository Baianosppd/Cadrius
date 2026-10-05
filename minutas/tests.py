import io
import zipfile
from datetime import date
from unittest import mock

from django.core.cache import cache
from django.db import connection
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from minutas import services
from minutas.models import Draft
from publications.models import OabWatch, Publication
from research.models import MonitoredCase

CNJ = '0000832-35.2018.4.01.3202'
TEXTO = ('Vistos. Ante o exposto, JULGO PROCEDENTE o pedido para condenar a ré ao pagamento de indenização. '
         'Intimem-se as partes para ciência.')


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org('Silva Advogados')
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.member.first_name, self.member.last_name = 'Ana', 'Lima'
        self.member.save()
        self.viewer = make_user('ver@x.com', self.org, role='VIEWER')
        OabWatch.objects.create(organization=self.org, numero='123456', uf='SP', responsavel=self.member)
        client = Contact.objects.create(organization=self.org, name='Maria Autora')
        case = MonitoredCase.objects.create(organization=self.org, cnj=CNJ, tribunal='trf1', client=client)
        self.pub = Publication.objects.create(
            organization=self.org, external_id='1', tribunal='TRF1', tipo='Intimação', orgao='1ª Vara Federal', cnj=CNJ, texto=TEXTO,
            partes=[{'nome': 'Maria Autora', 'polo': 'A'}, {'nome': 'Empresa Ré SA', 'polo': 'P'}], disponibilizada_em=date(2026, 3, 6),
            vencimento=date(2026, 3, 30), case=case, triage={'ato': 'Sentença', 'prazo_dias': 15, 'providencia': 'Avaliar apelação.',
                                                             'resumo': 'Procedência.'})
        self.c = APIClient()
        self.c.force_authenticate(self.member)

    def gen(self, **kw):
        body = {'modelo': 'builtin:resposta_cliente', 'fonte': 'publicacao', 'fonte_id': self.pub.pk, **kw}
        return self.c.post('/api/v1/minutas/', body, format='json')


class GenerateTests(Base):
    def test_modelo_preenchido_sem_ia(self):
        res = self.gen()
        self.assertEqual(res.status_code, 201, res.content)
        d = res.json()
        for expected in ('Prezado(a) Maria Autora', CNJ, 'Sentença', 'Avaliar apelação.', '30/03/2026', 'Ana Lima', 'Silva Advogados'):
            self.assertIn(expected, d['conteudo'])
        self.assertEqual((d['ia'], d['pendencias'], d['status']), ('', 0, 'rascunho'))
        self.assertEqual(d['citacoes'][0]['origem'], 'Publicação TRF1 de 06/03/2026')
        res = self.gen(modelo='builtin:peticao_juntada')
        self.assertIn('Empresa Ré SA', res.json()['conteudo'])                       # parte contrária = a outra parte
        self.assertIn('OAB 123456/SP', res.json()['conteudo'])
        self.assertIn('[COMPLETAR: Cidade]', res.json()['conteudo'])
        self.assertEqual(res.json()['pendencias'], 2)                                 # cidade + documento
        with connection.cursor() as cur:
            cur.execute('SELECT content, citations FROM minutas_draft LIMIT 1')
            self.assertTrue(all(v.startswith('enc::') for v in cur.fetchone()))
        self.assertTrue(AuditEvent.objects.filter(action='draft.created').exists())

    def test_ia_com_citacoes_conferidas(self):
        fake = {'texto': 'Minuta reescrita pela IA com base na sentença.',
                'trechos_citados': ['JULGO PROCEDENTE o pedido para condenar a ré', 'O réu confessou tudo em audiência realizada ontem.']}
        with mock.patch('documents.pipeline.pick_provider', return_value='GROQ'), \
                mock.patch('extraction.ai_wrapper.extract_fields_from_text', return_value=fake) as call, \
                mock.patch('billing.credits.check_credit_available', return_value=(True, '')), \
                mock.patch('billing.credits.consume_credit') as consume:
            res = self.gen(usar_ia=True)
        d = res.json()
        self.assertEqual((d['ia'], d['conteudo']), ('GROQ', fake['texto']))
        self.assertEqual([c['trecho'] for c in d['citacoes']], [fake['trechos_citados'][0]])   # a inventada foi descartada
        self.assertIn('1 trecho(s)', d['aviso'])
        consume.assert_called_once()
        self.assertIn('MINUTA BASE', call.call_args.args[2])

    def test_ia_bloqueada_cai_no_modelo(self):
        from aigov.guard import get_policy
        policy = get_policy(self.org)
        policy.ai_enabled = False
        policy.save()
        with mock.patch('documents.pipeline.pick_provider', return_value='GROQ'), \
                mock.patch('billing.credits.check_credit_available', return_value=(True, '')):
            d = self.gen(usar_ia=True).json()
        self.assertEqual(d['ia'], '')
        self.assertIn('bloqueada', d['aviso'])
        self.assertIn('Maria Autora', d['conteudo'])

    def test_fonte_documento(self):
        from documents.models import Document, DocumentExtraction
        doc = Document.objects.create(organization=self.org, nome='contrato.pdf', uploaded_by=self.member)
        DocumentExtraction.objects.create(document=doc, status='confirmed', excerpt='Contrato de prestação de serviços entre as partes.',
                                          fields={'numero_processo': CNJ, 'tipo_documento': 'Contrato',
                                                  'partes': [{'nome': 'Maria Autora'}, {'nome': 'Fornecedor X'}]})
        d = self.c.post('/api/v1/minutas/', {'modelo': 'builtin:notificacao_extrajudicial', 'fonte': 'documento', 'fonte_id': doc.pk},
                        format='json').json()
        self.assertIn('Notificado(a): Fornecedor X', d['conteudo'])
        self.assertIn('conforme contrato.pdf', d['conteudo'])
        self.assertEqual(len(self.c.get('/api/v1/minutas/', {'fonte': 'documento', 'fonte_id': doc.pk}).json()), 1)

    def test_erros_permissoes_e_isolamento(self):
        self.assertEqual(self.gen(modelo='builtin:nada').status_code, 400)
        self.assertEqual(self.gen(fonte='planeta').status_code, 400)
        self.assertEqual(self.gen(fonte_id=99999).status_code, 400)
        self.c.force_authenticate(self.viewer)
        self.assertEqual(self.gen().status_code, 403)
        self.c.force_authenticate(self.member)
        did = self.gen().json()['id']
        other = make_user('o@y.com', make_org('Outro'), role='OWNER')
        self.c.force_authenticate(other)
        self.assertEqual(self.c.get(f'/api/v1/minutas/{did}/').status_code, 404)
        self.assertEqual(self.c.post('/api/v1/minutas/', {'modelo': 'builtin:resposta_cliente', 'fonte': 'publicacao',
                                                          'fonte_id': self.pub.pk}, format='json').status_code, 400)


class ReviewAndExportTests(Base):
    def test_revisar_exige_sem_pendencias_e_edicao_volta_a_rascunho(self):
        d = self.gen(modelo='builtin:peticao_juntada').json()
        url = f'/api/v1/minutas/{d["id"]}/'
        self.assertEqual(self.c.patch(url, {'status': 'revisada'}, format='json').status_code, 400)
        fixed = d['conteudo'].replace('[COMPLETAR: Cidade]', 'São Paulo').replace('[COMPLETAR: Documento de origem]', 'procuração.pdf')
        res = self.c.patch(url, {'conteudo': fixed, 'status': 'revisada'}, format='json')
        self.assertEqual((res.json()['status'], res.json()['pendencias'], res.json()['revisada_por']), ('revisada', 0, 'Ana Lima'))
        self.assertEqual(self.c.patch(url, {'conteudo': fixed + '\nP.S.'}, format='json').json()['status'], 'rascunho')

    def test_docx(self):
        d = self.gen().json()
        Draft.objects.filter(pk=d['id']).update(content='Linha 1 <tag> & "aspas"\nLinha 2\x07')
        res = self.c.get(f'/api/v1/minutas/{d["id"]}/docx/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('.docx', res['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xml = z.read('word/document.xml').decode()
            self.assertIn('[Content_Types].xml', z.namelist())
        self.assertIn('Linha 1 &lt;tag&gt; &amp; "aspas"', xml)
        self.assertIn('<w:t xml:space="preserve">Linha 2</w:t>', xml)
        self.assertTrue(AuditEvent.objects.filter(action='draft.exported').exists())

    def test_modelos_do_escritorio(self):
        url = '/api/v1/minutas/modelos/'
        body = {'nome': 'Cobrança amigável', 'corpo': 'Prezado {{parte_contraria.nome}}, em nome de {{cliente.nome}} …'}
        self.assertEqual(self.c.post(url, body, format='json').status_code, 403)
        self.c.force_authenticate(self.owner)
        res = self.c.post(url, body, format='json')
        self.assertEqual(res.status_code, 201)
        key = res.json()['chave']
        listing = self.c.get(url).json()
        self.assertEqual(listing['modelos'][0]['chave'], key)
        self.assertTrue(any(v['chave'] == 'processo.cnj' for v in listing['variaveis']))
        d = self.gen(modelo=key).json()
        self.assertEqual(d['conteudo'], 'Prezado Empresa Ré SA, em nome de Maria Autora …')
        self.assertEqual(self.c.delete(f'{url}{res.json()["id"]}/').status_code, 204)

    def test_render_marca_o_que_falta(self):
        self.assertEqual(services.render('{{cliente.nome}} / {{x.y}}', {'cliente.nome': ''}),
                         '[COMPLETAR: Cliente] / [COMPLETAR: x.y]')
        self.assertEqual(services.extenso(date(2026, 3, 6)), '6 de março de 2026')
