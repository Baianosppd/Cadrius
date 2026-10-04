"""CAD-163/164: leitura automática de documentos (com revisão humana) e arquivos cifrados em repouso."""
import io
import os
import zipfile
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from aigov.guard import get_policy, set_global_switch
from audit.models import AuditEvent
from billing.credits import organization_credits_used
from cadrius.tests_security import make_org, make_user
from core import storage as cstorage
from core.pii import mask_text
from documents import pipeline
from documents.models import Document, DocumentExtraction
from privacy import consent
from tasks.models import UserTask

TEXT = ("Intimação no processo 0001234-56.2024.8.26.0100. Autor João da Silva, CPF 529.982.247-25, tel (11) 91234-5678, "
        "e-mail joao@example.com. Fica intimado a apresentar contestação no prazo de 15 dias.")
RESULT = {'document_type': 'DOCUMENTO_JURIDICO', 'confidence_score': 91, 'tipo_documento': 'INTIMACAO',
          'numero_processo': '0001234-56.2024.8.26.0100', 'partes': [{'papel': 'Autor', 'nome': 'João da Silva'}],
          'resumo': 'Intimação para contestar.', 'valor': None, 'proximos_passos': ['Preparar contestação'],
          'prazos': [{'descricao': 'Contestação', 'data': (timezone.now() + timedelta(days=15)).date().isoformat(), 'dias': 15, 'fatal': True}]}


def make_pdf(text: str) -> bytes:
    """PDF mínimo válido com uma linha de texto (para testar a leitura de verdade)."""
    stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode()
    objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
            b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
            b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    out, offsets = b'%PDF-1.4\n', []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % i + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    out += b''.join(b'%010d 00000 n \n' % o for o in offsets)
    return out + b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)


def make_docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('word/document.xml', f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


class SniffingTests(TestCase):
    def test_tipo_pelo_conteudo_nao_pela_extensao(self):
        self.assertEqual(pipeline.detect_kind(make_pdf('x')), 'pdf')
        self.assertEqual(pipeline.detect_kind(make_docx('x')), 'docx')
        self.assertEqual(pipeline.detect_kind(b'\x89PNG\r\n\x1a\n' + b'0' * 20), 'png')
        self.assertEqual(pipeline.detect_kind(b'\xff\xd8\xff\xe0' + b'0' * 20), 'jpeg')
        self.assertEqual(pipeline.detect_kind('Olá, mundo jurídico'.encode()), 'txt')
        self.assertEqual(pipeline.detect_kind(b'MZ\x90\x00\x03\x00\x00\x00' + os.urandom(64)), '')       # executável com nome .pdf
        self.assertEqual(pipeline.detect_kind(b'PK\x03\x04' + b'0' * 30), '')                            # zip qualquer

    def test_leitura_de_pdf_docx_txt(self):
        text, ocr = pipeline.extract_text(make_pdf('Intimacao prazo de quinze dias para contestar o pedido'), 'pdf')
        self.assertIn('quinze dias', text)
        self.assertFalse(ocr)
        self.assertIn('Contrato de honorarios', pipeline.extract_text(make_docx('Contrato de honorarios'), 'docx')[0])
        self.assertEqual(pipeline.extract_text('texto simples'.encode(), 'txt')[0], 'texto simples')

    def test_escaneado_sem_ocr_explica_o_motivo(self):
        blank = make_pdf('')
        with mock.patch.object(pipeline, 'ocr_available', return_value=False):
            with self.assertRaises(pipeline.Skip) as ctx:
                pipeline.extract_text(blank, 'pdf')
        self.assertIn('OCR', str(ctx.exception))
        with mock.patch.object(pipeline, 'ocr_available', return_value=True), \
                mock.patch.object(pipeline, '_ocr_pdf', return_value='texto vindo do ocr'):
            self.assertEqual(pipeline.extract_text(blank, 'pdf'), ('texto vindo do ocr', True))

    def test_mascara_de_pii_preserva_o_numero_do_processo(self):
        masked = mask_text(TEXT)
        for secret in ('529.982.247-25', '91234-5678', 'joao@example.com'):
            self.assertNotIn(secret, masked)
        self.assertIn('0001234-56.2024.8.26.0100', masked)
        self.assertIn('[CPF]', masked)


class FileEncryptionTests(TestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')

    def doc(self, content=b'conteudo sigiloso do contrato', name='contrato.txt'):
        return Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Contrato', tipo='contrato',
                                       status='pronto', arquivo=SimpleUploadedFile(name, content))

    def test_arquivo_fica_cifrado_no_disco_e_legivel_pela_aplicacao(self):
        doc = self.doc()
        self.addCleanup(lambda: doc.arquivo.storage.delete(doc.arquivo.name))
        with open(doc.arquivo.path, 'rb') as fh:
            raw = fh.read()
        self.assertTrue(raw.startswith(cstorage.MAGIC))
        self.assertNotIn(b'sigiloso', raw)
        self.assertEqual(cstorage.read_all(doc.arquivo), b'conteudo sigiloso do contrato')

    def test_legado_em_texto_puro_continua_legivel_e_encrypt_files_cifra(self):
        from django.core.management import call_command
        doc = self.doc()
        self.addCleanup(lambda: doc.arquivo.storage.delete(doc.arquivo.name))
        with open(doc.arquivo.path, 'wb') as fh:                       # simula arquivo antigo, sem cifra
            fh.write(b'legado em texto puro')
        self.assertEqual(cstorage.read_all(doc.arquivo), b'legado em texto puro')
        out = io.StringIO()
        call_command('encrypt_files', '--dry-run', stdout=out)
        self.assertIn('1 em texto puro', out.getvalue())
        call_command('encrypt_files', stdout=io.StringIO())
        with open(doc.arquivo.path, 'rb') as fh:
            self.assertTrue(fh.read().startswith(cstorage.MAGIC))
        self.assertEqual(cstorage.read_all(doc.arquivo), b'legado em texto puro')
        out = io.StringIO()
        call_command('encrypt_files', stdout=out)
        self.assertIn('0 cifrados agora', out.getvalue())               # idempotente


class PipelineBase(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.org.plan.max_ai_extractions = 50
        self.org.plan.save()
        self.created = []
        env = mock.patch.dict(os.environ, {'GROQ_API_KEY': 'k', 'GEMINI_API_KEY': '', 'OPENAI_API_KEY': ''})
        env.start()
        self.addCleanup(env.stop)
        self.ai = mock.patch('extraction.ai_wrapper.extract_fields_from_text', return_value=dict(RESULT))
        self.ai_mock = self.ai.start()
        self.addCleanup(self.ai.stop)
        enq = mock.patch('documents.pipeline.enqueue_processing')    # nos testes de pipeline, roda-se na mão
        enq.start()
        self.addCleanup(enq.stop)

    def doc(self, content=TEXT.encode(), name='intimacao.txt'):
        doc = Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Intimação', tipo='outro',
                                      status='processando', arquivo=SimpleUploadedFile(name, content))
        self.addCleanup(lambda: doc.arquivo.storage.delete(doc.arquivo.name))
        return doc

    def run_pipeline(self, doc):
        return pipeline.process_document(doc.pk, self.owner.pk)


class PipelineTests(PipelineBase):
    def test_fluxo_feliz_mascara_a_pii_cobra_um_credito_e_fica_para_revisao(self):
        doc = self.doc()
        self.assertEqual(self.run_pipeline(doc), 'review')
        ex = DocumentExtraction.objects.get(document=doc)
        self.assertEqual((ex.status, ex.provider, ex.confidence, ex.detected_kind), ('review', 'GROQ', 91, 'txt'))
        self.assertEqual(ex.fields['tipo_documento'], 'INTIMACAO')
        sent = self.ai_mock.call_args.args[0]
        self.assertNotIn('529.982.247-25', sent)
        self.assertNotIn('joao@example.com', sent)
        self.assertIn('0001234-56.2024.8.26.0100', sent)
        self.assertEqual(organization_credits_used(self.org), 1)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'pronto')
        self.assertTrue(AuditEvent.objects.filter(action='document.extracted').exists())
        with connection.cursor() as cur:                                  # dados extraídos cifrados no banco
            cur.execute('SELECT fields FROM documents_documentextraction')
            raw = cur.fetchone()[0]
        self.assertTrue(raw.startswith('enc::'))
        self.assertNotIn('João', raw)

    def test_leitura_real_de_pdf_e_docx_passa_pelo_pipeline(self):
        for content, name in ((make_pdf('Intimacao no processo 0001234-56.2024.8.26.0100 prazo de quinze dias'), 'a.pdf'),
                              (make_docx('Contrato de honorarios advocaticios entre as partes'), 'b.docx')):
            doc = self.doc(content, name)
            self.assertEqual(self.run_pipeline(doc), 'review', name)

    def test_arquivo_disfarcado_e_recusado_sem_chamar_a_ia(self):
        doc = self.doc(b'MZ\x90\x00' + os.urandom(200), 'inocente.pdf')
        self.assertEqual(self.run_pipeline(doc), 'skipped')
        ex = DocumentExtraction.objects.get(document=doc)
        self.assertEqual(ex.status, 'skipped')
        self.assertIn('não suportado', ex.message)
        self.ai_mock.assert_not_called()

    def test_ia_sem_resultado_falha_sem_cobrar(self):
        self.ai_mock.return_value = None
        doc = self.doc()
        self.assertEqual(self.run_pipeline(doc), 'failed')
        self.assertEqual(DocumentExtraction.objects.get(document=doc).status, 'failed')
        self.assertEqual(organization_credits_used(self.org), 0)

    def test_sem_provedor_sem_credito_com_ia_pausada_ou_politica(self):
        with mock.patch.dict(os.environ, {'GROQ_API_KEY': ''}):
            doc = self.doc()
            self.assertEqual(self.run_pipeline(doc), 'skipped')
            self.assertIn('provedor', DocumentExtraction.objects.get(document=doc).message)
        self.org.plan.max_ai_extractions = 0
        self.org.plan.save()
        doc2 = self.doc()
        self.assertEqual(self.run_pipeline(doc2), 'skipped')
        self.assertIn('créditos', DocumentExtraction.objects.get(document=doc2).message)
        self.org.plan.max_ai_extractions = 50
        self.org.plan.save()
        self.org.subscription_status = 'canceled'
        self.org.save()
        doc3 = self.doc()
        self.run_pipeline(doc3)
        self.assertIn('Assinatura pendente', DocumentExtraction.objects.get(document=doc3).message)
        self.org.subscription_status = 'active'
        self.org.save()
        set_global_switch(False, reason='teste')
        doc4 = self.doc()
        self.assertEqual(self.run_pipeline(doc4), 'ai_blocked')
        set_global_switch(True)
        self.ai_mock.assert_not_called()

    def test_provedor_respeita_a_politica_e_a_ordem_barato_primeiro(self):
        with mock.patch.dict(os.environ, {'GROQ_API_KEY': 'k', 'GEMINI_API_KEY': 'g', 'OPENAI_API_KEY': 'o'}):
            self.assertEqual(pipeline.pick_provider(get_policy(self.org)), 'GROQ')
            policy = get_policy(self.org)
            policy.allowed_providers = ['OPENAI', 'GEMINI']
            self.assertEqual(pipeline.pick_provider(policy), 'GEMINI')

    @override_settings(CLAMAV_HOST='clam.local')
    def test_antivirus_bloqueia_infectado_e_falha_fechado_se_estiver_fora(self):
        doc = self.doc()
        fake = mock.MagicMock()
        fake.__enter__.return_value.recv.return_value = b'stream: Eicar-Test-Signature FOUND\0'
        with mock.patch('documents.pipeline.socket.create_connection', return_value=fake):
            self.assertEqual(self.run_pipeline(doc), 'blocked')
        self.assertIn('antivírus', DocumentExtraction.objects.get(document=doc).message)
        self.assertTrue(AuditEvent.objects.filter(action='document.blocked').exists())
        fake.__enter__.return_value.recv.return_value = b'stream: OK\0'
        with mock.patch('documents.pipeline.socket.create_connection', return_value=fake):
            self.assertEqual(self.run_pipeline(doc), 'review')
        with mock.patch('documents.pipeline.socket.create_connection', side_effect=OSError('down')):
            self.assertEqual(self.run_pipeline(doc), 'skipped')
        self.assertIn('Antivírus indisponível', DocumentExtraction.objects.get(document=doc).message)

    def test_reprocessar_nao_sobrescreve_o_que_foi_confirmado(self):
        doc = self.doc()
        self.run_pipeline(doc)
        ex = DocumentExtraction.objects.get(document=doc)
        pipeline.confirm(ex, self.owner, {'resumo': 'Revisado pelo advogado', 'prazos': []})
        self.assertEqual(self.run_pipeline(doc), 'confirmed')
        ex.refresh_from_db()
        self.assertEqual(ex.fields['resumo'], 'Revisado pelo advogado')


class ApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.viewer = make_user('v@example.com', self.org, role='VIEWER')
        for u in (self.owner, self.viewer):
            for d in consent.current_documents(consent.REQUIRED_KINDS):
                consent.record_consent(u, d)
        self.client.force_authenticate(self.owner)
        doc = Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Intimação', tipo='outro', status='processando',
                                      arquivo=SimpleUploadedFile('i.txt', TEXT.encode()))
        self.addCleanup(lambda: doc.arquivo.storage.delete(doc.arquivo.name))
        self.doc = doc
        self.ex = DocumentExtraction.objects.create(document=doc, status='review', stage='review', fields=dict(RESULT), confidence=91, provider='GROQ')
        self.base = f'/api/v1/documentos/{doc.pk}/extraction/'

    def test_upload_cria_registro_na_fila_e_enfileira_depois_do_commit(self):
        with mock.patch('core.queue.async_task') as q, self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post('/api/v1/documentos/', {'nome': 'Novo', 'tipo': 'contrato', 'status': 'processando',
                                                           'arquivo': SimpleUploadedFile('n.txt', b'ola mundo juridico')}, format='multipart')
        self.assertEqual(resp.status_code, 201, resp.data)
        ex = DocumentExtraction.objects.get(document_id=resp.data['id'])
        self.assertEqual(ex.status, 'pending')
        self.assertEqual(q.call_args.args[:2], ('documents.pipeline.process_document', resp.data['id']))
        Document.objects.get(pk=resp.data['id']).arquivo.storage.delete(Document.objects.get(pk=resp.data['id']).arquivo.name)

    def test_upload_recusa_arquivo_acima_do_limite(self):
        with override_settings(DOCUMENT_MAX_BYTES=10):
            resp = self.client.post('/api/v1/documentos/', {'nome': 'G', 'tipo': 'outro', 'status': 'processando',
                                                           'arquivo': SimpleUploadedFile('g.txt', b'x' * 50)}, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('arquivo', resp.data)

    def test_ver_a_leitura_e_isolamento_entre_escritorios(self):
        data = self.client.get(self.base).data
        self.assertEqual((data['status'], data['fields']['tipo_documento'], data['provider']), ('review', 'INTIMACAO', 'GROQ'))
        other_org = make_org('Outro')
        stranger = make_user('x@example.com', other_org, role='OWNER')
        self.client.force_authenticate(stranger)
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.assertEqual(self.client.post(self.base + 'confirm/', {'fields': {}}, format='json').status_code, 404)

    def test_confirmar_cria_tarefas_dos_prazos_e_audita(self):
        resp = self.client.post(self.base + 'confirm/', {'fields': {'resumo': 'Corrigido'}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], 'confirmed')
        self.assertEqual(len(resp.data['tasks_created']), 1)
        task = UserTask.objects.get()
        self.assertEqual((task.titulo, task.priority, task.responsavel_id, task.sincronizar), ('Prazo: Contestação', 'alta', self.owner.pk, False))
        self.assertEqual(timezone.localtime(task.scheduled_at).hour, 9)
        self.ex.refresh_from_db()
        self.assertEqual((self.ex.fields['resumo'], self.ex.reviewed_by_id), ('Corrigido', self.owner.pk))
        self.assertTrue(AuditEvent.objects.filter(action='document.extraction_confirmed').exists())

    def test_prazo_sem_data_nao_vira_tarefa_e_fields_invalido(self):
        bad = self.client.post(self.base + 'confirm/', {'fields': 'texto'}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.client.post(self.base + 'confirm/', {'fields': {'prazos': [{'descricao': 'Sem data', 'data': None, 'dias': 10}]}}, format='json')
        self.assertFalse(UserTask.objects.exists())

    def test_so_quem_pode_revisar_e_estados_invalidos(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.post(self.base + 'confirm/', {'fields': {}}, format='json').status_code, 403)
        self.assertEqual(self.client.post(self.base + 'reprocess/').status_code, 403)
        self.assertEqual(self.client.get(self.base).status_code, 200)             # leitor pode ver
        self.client.force_authenticate(self.owner)
        self.ex.status = 'failed'
        self.ex.save()
        self.assertEqual(self.client.post(self.base + 'confirm/', {'fields': {}}, format='json').status_code, 409)

    def test_reprocessar_enfileira_e_nao_mexe_no_confirmado(self):
        self.ex.status = 'failed'
        self.ex.save()
        with mock.patch('documents.pipeline.enqueue_processing') as enq:
            resp = self.client.post(self.base + 'reprocess/')
        self.assertEqual(resp.status_code, 202)
        enq.assert_called_once_with(self.doc.pk, self.owner.pk)
        self.ex.refresh_from_db()
        self.assertEqual(self.ex.status, 'pending')
        self.ex.status = 'confirmed'
        self.ex.save()
        self.assertEqual(self.client.post(self.base + 'reprocess/').status_code, 409)

    def test_detalhe_do_documento_com_cliente_e_isolamento(self):
        from documents.models import ClientDocument
        ClientDocument.objects.create(nome_cliente='Maria Oliveira', documento=self.doc)
        data = self.client.get(f'/api/v1/documentos/{self.doc.pk}/').data
        self.assertEqual((data['nome'], data['cliente'], data['tem_arquivo']), ('Intimação', 'Maria Oliveira', True))
        self.client.force_authenticate(make_user('x@example.com', make_org('Outro'), role='OWNER'))
        self.assertEqual(self.client.get(f'/api/v1/documentos/{self.doc.pk}/').status_code, 404)

    def test_download_devolve_o_arquivo_decifrado(self):
        resp = self.client.get(f'/api/v1/documentos/{self.doc.pk}/download/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b''.join(resp.streaming_content), TEXT.encode())
