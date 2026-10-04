"""CAD-165: memória, feedback, regras aprendidas, matriz de autonomia e leitura local."""
import os
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditEvent
from brain import autonomy, feedback, memory
from brain.embeddings import cosine, embed
from brain.local import local_extract
from brain.models import AIFeedback, AutonomyLevel, AutonomyProposal, MemoryItem, OfficeRule
from cadrius.tests_security import make_org, make_user
from documents import pipeline
from documents.models import Document, DocumentExtraction
from documents.tests_pipeline import RESULT, TEXT
from privacy import consent
from tasks.models import UserTask


class LocalAndMemoryTests(TestCase):
    def test_leitura_local_acha_processo_tipo_e_prazos(self):
        r = local_extract("Fica intimado para contestar no prazo de 15 (quinze) dias úteis. Proc. 0001234-56.2024.8.26.0100. "
                          "Audiência designada, prazo até 20/12/2026.")
        self.assertEqual((r['tipo_documento'], r['numero_processo']), ('INTIMACAO', '0001234-56.2024.8.26.0100'))
        self.assertIn({'descricao': 'Prazo indicado no texto (úteis)', 'data': None, 'dias': 15, 'fatal': False}, r['prazos'])
        self.assertTrue(any(p['data'] == '2026-12-20' for p in r['prazos']))
        self.assertLess(r['confidence_score'], 50)
        self.assertEqual(local_extract('texto qualquer sem nada')['tipo_documento'], 'OUTRO')

    def test_memoria_acha_parecidos_so_do_proprio_escritorio(self):
        a, b = make_org('A'), make_org('B')
        memory.remember(a, 'template', 'Contestação trabalhista com pedido de improcedência das horas extras', title='Contestação')
        memory.remember(a, 'template', 'Contrato de honorários advocatícios com cláusula de êxito', title='Honorários')
        memory.remember(b, 'template', 'Contestação trabalhista da outra banca', title='Contestação B')
        found = memory.similar(a, 'preciso contestar horas extras em ação trabalhista', k=3)
        self.assertEqual(found[0][1].title, 'Contestação')
        self.assertTrue(all(i.organization_id == a.pk for _, i in found))        # nunca vaza outro escritório
        self.assertEqual(memory.similar(a, 'xyzzy plugh', k=3), [])

    def test_embedding_e_cifrado_no_banco_e_normalizado(self):
        org = make_org()
        item = memory.remember(org, 'note', 'Nota sigilosa do escritório sobre estratégia')
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT text, embedding FROM brain_memoryitem')
            text_raw, emb_raw = cur.fetchone()
        self.assertTrue(text_raw.startswith('enc::') and emb_raw.startswith('enc::'))
        self.assertAlmostEqual(cosine(item.embedding, item.embedding), 1.0, places=2)
        self.assertEqual(len(embed('qualquer')), 384)


class FeedbackAndRulesTests(TestCase):
    def setUp(self):
        self.org = make_org()
        self.user = make_user('o@example.com', self.org, role='OWNER')

    def edit(self, frm, to, n=1):
        for _ in range(n):
            feedback.record_review(self.org, self.user, 'document_extraction', 'document:1',
                                   {'tipo_documento': frm, 'resumo': 'a'}, {'tipo_documento': to, 'resumo': 'a'})

    def test_aprovar_sem_mudar_e_editar(self):
        fb = feedback.record_review(self.org, self.user, 'document_extraction', 'document:1', {'resumo': 'a', 'partes': []}, {'resumo': 'a', 'partes': []})
        self.assertEqual((fb.decision, fb.changes), ('approved', []))
        fb = feedback.record_review(self.org, self.user, 'document_extraction', 'document:2', {'resumo': 'a', 'partes': []},
                                    {'resumo': 'b', 'partes': [{'nome': 'x'}]})
        self.assertEqual(fb.decision, 'edited')
        self.assertEqual({c['field'] for c in fb.changes}, {'resumo', 'partes'})

    def test_correcao_repetida_vira_proposta_e_so_vale_depois_de_aprovada(self):
        self.edit('OUTRO', 'INTIMACAO', n=4)
        self.assertEqual(feedback.mine_rules(self.org), [])                   # evidência insuficiente
        self.edit('OUTRO', 'INTIMACAO', n=1)
        rules = feedback.mine_rules(self.org)
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual((rule.status, rule.evidence), ('proposed', 5))
        out, applied = feedback.apply_rules(self.org, {'tipo_documento': 'OUTRO'})
        self.assertEqual((out['tipo_documento'], applied), ('OUTRO', []))     # proposta ainda não vale
        feedback.decide_rule(rule, self.user, 'approve')
        out, applied = feedback.apply_rules(self.org, {'tipo_documento': 'OUTRO'})
        self.assertEqual(out['tipo_documento'], 'INTIMACAO')
        self.assertEqual(len(applied), 1)
        self.assertTrue(AuditEvent.objects.filter(action='ai.rule_decided').exists())
        feedback.decide_rule(rule, self.user, 'disable')
        self.assertEqual(feedback.apply_rules(self.org, {'tipo_documento': 'OUTRO'})[0]['tipo_documento'], 'OUTRO')
        self.assertEqual(feedback.mine_rules(self.org), [])                   # não repropõe a mesma regra

    def test_regras_sao_isoladas_por_escritorio(self):
        other = make_org('Outro')
        rule = OfficeRule.objects.create(organization=other, field='tipo_documento', from_value='OUTRO', to_value='SENTENCA', status='active')
        self.assertEqual(feedback.apply_rules(self.org, {'tipo_documento': 'OUTRO'})[0]['tipo_documento'], 'OUTRO')
        self.assertEqual(rule.organization_id, other.pk)


class AutonomyTests(TestCase):
    def setUp(self):
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')

    def feed(self, n, decision='approved', kind='document_extraction'):
        for i in range(n):
            AIFeedback.objects.create(organization=self.org, user=self.owner, action_kind=kind, decision=decision, subject=f'document:{i}')

    def test_padrao_e_r4_nunca_automatico(self):
        self.assertEqual(autonomy.resolve(self.org, 'document_extraction'), 'review')
        for kind in ('petition_filing', 'fatal_deadline', 'payment', 'data_deletion'):
            with self.assertRaises(autonomy.AutonomyError):
                autonomy.set_level(self.org, kind, 'auto', self.owner)
            with self.assertRaises(autonomy.AutonomyError):
                autonomy.set_level(self.org, kind, 'auto_undo', self.owner)
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.set_level(self.org, 'client_message', 'auto', self.owner)     # R3 também fica em revisão
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.set_level(self.org, 'document_extraction', 'auto_undo', self.owner)   # modo não previsto p/ a ação
        self.assertEqual(autonomy.set_level(self.org, 'document_extraction', 'auto', self.owner), 'auto')
        self.assertTrue(AuditEvent.objects.filter(action='ai.autonomy_changed').exists())

    def test_promocao_so_sugere_com_criterios_objetivos(self):
        self.feed(29)
        self.assertEqual(autonomy.evaluate_promotions(self.org), [])             # volume insuficiente
        self.feed(1)
        proposals = autonomy.evaluate_promotions(self.org)
        self.assertEqual([(p.action_kind, p.from_mode, p.to_mode) for p in proposals], [('document_extraction', 'review', 'auto')])
        self.assertEqual(autonomy.resolve(self.org, 'document_extraction'), 'review')    # sugerir NÃO muda nada
        self.assertEqual(autonomy.evaluate_promotions(self.org), [])             # não duplica
        autonomy.decide_proposal(proposals[0], self.owner, approve=True)
        self.assertEqual(autonomy.resolve(self.org, 'document_extraction'), 'auto')
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.decide_proposal(proposals[0], self.owner, approve=True)

    def test_taxa_baixa_rejeicao_ou_desfazer_impedem_a_sugestao(self):
        self.feed(28)
        self.feed(2, 'edited')                                                    # 93% < 95%
        self.assertEqual(autonomy.evaluate_promotions(self.org), [])
        AIFeedback.objects.all().delete()
        self.feed(40)
        self.feed(1, 'undone')
        self.assertEqual(autonomy.evaluate_promotions(self.org), [])
        AIFeedback.objects.all().delete()
        self.feed(40)
        self.feed(1, 'rejected')
        self.assertEqual(autonomy.evaluate_promotions(self.org), [])

    def test_feedback_antigo_fora_da_janela_nao_conta(self):
        self.feed(40)
        AIFeedback.objects.update(created_at=timezone.now() - timedelta(days=90))
        self.assertEqual(autonomy.stats(self.org, 'document_extraction')['samples'], 0)

    def test_erro_grave_rebaixa_na_hora(self):
        autonomy.set_level(self.org, 'document_extraction', 'auto', self.owner)
        self.assertTrue(autonomy.report_error(self.org, 'document_extraction', 'prazo errado', self.owner))
        self.assertEqual(autonomy.resolve(self.org, 'document_extraction'), 'review')
        self.assertFalse(autonomy.report_error(self.org, 'document_extraction', 'já estava em revisão'))


class BrainPipelineIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.org.plan.max_ai_extractions = 100
        self.org.plan.save()
        for p in (mock.patch.dict(os.environ, {'GROQ_API_KEY': 'k'}), mock.patch('documents.pipeline.enqueue_processing'),
                  mock.patch('extraction.ai_wrapper.extract_fields_from_text', return_value=dict(RESULT))):
            p.start()
            self.addCleanup(p.stop)
        self.ai = __import__('extraction.ai_wrapper', fromlist=['x'])

    def doc(self, text=TEXT):
        d = Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Doc', tipo='outro', status='processando',
                                    arquivo=SimpleUploadedFile('d.txt', text.encode()))
        self.addCleanup(lambda: d.arquivo.storage.delete(d.arquivo.name))
        return d

    def test_confirmar_gera_feedback_memoria_e_a_proxima_leitura_recebe_exemplo(self):
        d = self.doc()
        pipeline.process_document(d.pk, self.owner.pk)
        ex = DocumentExtraction.objects.get(document=d)
        self.assertTrue(ex.original_fields and ex.excerpt)
        self.assertNotIn('529.982.247-25', ex.excerpt)                        # excerto já mascarado
        edited = {'tipo_documento': 'DECISAO'}
        pipeline.confirm(ex, self.owner, edited)
        fb = AIFeedback.objects.get()
        self.assertEqual((fb.decision, fb.changes[0]['field'], fb.changes[0]['to']), ('edited', 'tipo_documento', 'DECISAO'))
        item = MemoryItem.objects.get()
        self.assertEqual((item.kind, item.payload['tipo_documento']), ('extraction_example', 'DECISAO'))
        # segunda leitura parecida: o exemplo aprovado entra no prompt (few-shot) e o texto do exemplo está mascarado
        d2 = self.doc(TEXT.replace('João', 'José'))
        with mock.patch('extraction.ai_wrapper.extract_fields_from_text', return_value=dict(RESULT)) as ai:
            pipeline.process_document(d2.pk, self.owner.pk)
        prompt = ai.call_args.args[2]
        self.assertIn('Exemplos de leituras já aprovadas', prompt)
        self.assertIn('DECISAO', prompt)
        self.assertNotIn('529.982.247-25', prompt)

    def test_regra_ativa_corrige_a_proxima_leitura(self):
        OfficeRule.objects.create(organization=self.org, field='tipo_documento', from_value='INTIMACAO', to_value='DECISAO', status='active')
        d = self.doc()
        pipeline.process_document(d.pk, self.owner.pk)
        ex = DocumentExtraction.objects.get(document=d)
        self.assertEqual(ex.fields['tipo_documento'], 'DECISAO')
        self.assertIn('regra(s) do escritório', ex.message)

    def test_autonomia_auto_confirma_so_com_ia_real_e_confianca_alta_e_pode_ser_desfeita(self):
        autonomy.set_level(self.org, 'document_extraction', 'auto', self.owner)
        autonomy.set_level(self.org, 'deadline_task', 'auto_undo', self.owner)
        d = self.doc()
        self.assertEqual(pipeline.process_document(d.pk, self.owner.pk), 'auto_confirmed')
        ex = DocumentExtraction.objects.get(document=d)
        self.assertEqual((ex.status, ex.reviewed_by_id), ('confirmed', None))
        self.assertEqual(UserTask.objects.count(), 1)
        self.assertIn('desfazer em até 24 h', ex.message)
        pipeline.undo_auto(ex, self.owner)
        ex.refresh_from_db()
        self.assertEqual((ex.status, UserTask.objects.count()), ('review', 0))
        self.assertEqual(autonomy.resolve(self.org, 'document_extraction'), 'review')     # rebaixada
        self.assertEqual(autonomy.resolve(self.org, 'deadline_task'), 'review')
        self.assertTrue(AIFeedback.objects.filter(decision='undone').exists())
        with self.assertRaises(ValueError):
            pipeline.undo_auto(ex, self.owner)                                              # já não está confirmada

    def test_confianca_baixa_ou_rascunho_local_nao_confirmam_sozinhos(self):
        autonomy.set_level(self.org, 'document_extraction', 'auto', self.owner)
        low = dict(RESULT, confidence_score=60)
        with mock.patch('extraction.ai_wrapper.extract_fields_from_text', return_value=low):
            self.assertEqual(pipeline.process_document(self.doc().pk, self.owner.pk), 'review')
        with mock.patch.dict(os.environ, {'GROQ_API_KEY': ''}):
            self.assertEqual(pipeline.process_document(self.doc().pk, self.owner.pk), 'review')   # local nunca é automático

    def test_desfazer_so_vale_para_confirmacao_automatica_dentro_de_24h(self):
        autonomy.set_level(self.org, 'document_extraction', 'auto', self.owner)
        d = self.doc()
        pipeline.process_document(d.pk, self.owner.pk)
        ex = DocumentExtraction.objects.get(document=d)
        DocumentExtraction.objects.filter(pk=ex.pk).update(reviewed_at=timezone.now() - timedelta(hours=25))
        ex.refresh_from_db()
        with self.assertRaises(ValueError):
            pipeline.undo_auto(ex, self.owner)
        other = self.doc()
        pipeline.process_document(other.pk, self.owner.pk)
        human = DocumentExtraction.objects.get(document=other)
        human.reviewed_by = self.owner
        human.status = 'confirmed'
        human.save()
        with self.assertRaises(ValueError):
            pipeline.undo_auto(human, self.owner)                                           # confirmação humana não se "desfaz" aqui


class BrainApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        self.admin = make_user('a@example.com', self.org, role='ADMIN')
        self.member = make_user('m@example.com', self.org, role='MEMBER')
        for u in (self.owner, self.admin, self.member):
            for doc in consent.current_documents(consent.REQUIRED_KINDS):
                consent.record_consent(u, doc)
        self.base = '/api/v1/brain/'
        self.client.force_authenticate(self.owner)

    def test_central_de_aprovacoes_agrega_o_que_depende_de_decisao(self):
        d = Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Intimação X', tipo='outro', status='pronto',
                                    arquivo=SimpleUploadedFile('i.txt', b'x' * 30))
        self.addCleanup(lambda: d.arquivo.storage.delete(d.arquivo.name))
        DocumentExtraction.objects.create(document=d, status='review', confidence=88, fields={'prazos': [{}, {}]})
        OfficeRule.objects.create(organization=self.org, field='tipo_documento', from_value='A', to_value='B', evidence=5)
        AutonomyProposal.objects.create(organization=self.org, action_kind='document_extraction', from_mode='review', to_mode='auto',
                                        samples=31, approval_rate='0.97')
        data = self.client.get(self.base + 'approvals/').data
        self.assertEqual([r['nome'] for r in data['document_reviews']], ['Intimação X'])
        self.assertEqual(data['document_reviews'][0]['prazos'], 2)
        self.assertEqual(len(data['rules_proposed']), 1)
        self.assertEqual(data['autonomy_proposals'][0]['to_mode'], 'auto')
        self.client.force_authenticate(self.member)                              # membro vê só as leituras, não as decisões de gestão
        member_view = self.client.get(self.base + 'approvals/').data
        self.assertEqual((len(member_view['document_reviews']), member_view['rules_proposed'], member_view['autonomy_proposals']), (1, [], []))

    def test_decidir_regra_so_gestor_e_isolado_por_escritorio(self):
        rule = OfficeRule.objects.create(organization=self.org, field='tipo_documento', from_value='A', to_value='B', evidence=5)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(f'{self.base}rules/{rule.pk}/decide/', {'decision': 'approve'}, format='json').status_code, 403)
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f'{self.base}rules/{rule.pk}/decide/', {'decision': 'approve'}, format='json')
        self.assertEqual((resp.status_code, resp.data['status']), (200, 'active'))
        self.assertEqual(self.client.post(f'{self.base}rules/{rule.pk}/decide/', {'decision': 'xx'}, format='json').status_code, 400)
        self.client.force_authenticate(make_user('x@example.com', make_org('Outro'), role='OWNER'))
        self.assertEqual(self.client.post(f'{self.base}rules/{rule.pk}/decide/', {'decision': 'disable'}, format='json').status_code, 404)

    def test_matriz_so_o_dono_muda_e_r4_e_travado(self):
        data = self.client.get(self.base + 'autonomy/').data
        by = {r['action_kind']: r for r in data['levels']}
        self.assertTrue(by['petition_filing']['locked'])
        self.assertEqual(by['document_extraction']['allowed_modes'], ['off', 'review', 'auto'])
        self.assertEqual(data['criteria']['min_samples'], 30)
        self.assertEqual(self.client.put(self.base + 'autonomy/document_extraction/', {'mode': 'auto'}, format='json').status_code, 200)
        self.assertEqual(self.client.put(self.base + 'autonomy/petition_filing/', {'mode': 'auto'}, format='json').status_code, 400)
        self.assertEqual(self.client.put(self.base + 'autonomy/inexistente/', {'mode': 'auto'}, format='json').status_code, 400)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.put(self.base + 'autonomy/document_extraction/', {'mode': 'review'}, format='json').status_code, 403)

    def test_decidir_promocao_so_o_dono(self):
        p = AutonomyProposal.objects.create(organization=self.org, action_kind='document_extraction', from_mode='review', to_mode='auto',
                                            samples=31, approval_rate='0.97')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'{self.base}autonomy/proposals/{p.pk}/decide/', {'decision': 'approve'}, format='json').status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(f'{self.base}autonomy/proposals/{p.pk}/decide/', {'decision': 'approve'}, format='json').status_code, 200)
        self.assertEqual(AutonomyLevel.objects.get().mode, 'auto')
        self.assertEqual(self.client.post(f'{self.base}autonomy/proposals/{p.pk}/decide/', {'decision': 'approve'}, format='json').status_code, 409)

    def test_memoria_cadastrar_buscar_e_apagar(self):
        resp = self.client.post(self.base + 'memory/', {'kind': 'template', 'title': 'Contestação trabalhista', 'text': 'Modelo de contestação com horas extras e intervalo intrajornada'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        found = self.client.get(self.base + 'memory/search/', {'q': 'contestar horas extras'}).data
        self.assertEqual(found[0]['title'], 'Contestação trabalhista')
        self.assertEqual(self.client.get(self.base + 'memory/search/', {'q': 'ab'}).data, [])
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(self.base + 'memory/', {'kind': 'note', 'title': 'x', 'text': 'y'}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(f"{self.base}memory/{resp.data['id']}/").status_code, 403)
        other = make_user('x@example.com', make_org('Outro'), role='OWNER')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.base + 'memory/search/', {'q': 'contestar horas extras'}).data, [])   # isolamento
        self.assertEqual(self.client.delete(f"{self.base}memory/{resp.data['id']}/").status_code, 404)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete(f"{self.base}memory/{resp.data['id']}/").status_code, 204)

    def test_comando_diario_propoe_regras_e_sugere_promocao(self):
        from io import StringIO

        from django.core.management import call_command
        for _ in range(5):
            feedback.record_review(self.org, self.owner, 'document_extraction', 'document:1', {'tipo_documento': 'OUTRO'}, {'tipo_documento': 'DECISAO'})
        for i in range(120):    # 120 aprovadas + 5 editadas = 96% de aprovação sem edição
            AIFeedback.objects.create(organization=self.org, action_kind='document_extraction', decision='approved', subject=f'd{i}')
        out = StringIO()
        call_command('brain_evaluate', stdout=out)
        self.assertIn('1 regra(s) proposta(s), 1 sugestão', out.getvalue())
