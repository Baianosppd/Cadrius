"""CAD-226: documento escolhido no Assistente (extração e planejamento)."""
from django.core.files.uploadedfile import SimpleUploadedFile

from assistant.models import Message
from assistant.tests_h import BASE, Base, text, tool
from documents.models import Document, DocumentExtraction


class DocumentInAssistantTests(Base):
    def setUp(self):
        super().setUp()
        body = ('CONTRATO DE HONORÁRIOS. Contratante: Maria Cliente. Valor: R$ 5.000,00. Vencimento: 10/11/2026. ' * 200).encode()
        self.doc = Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Contrato "Maria"', tipo='contrato',
                                           status='pronto', arquivo=SimpleUploadedFile('contrato.txt', body))
        self.addCleanup(lambda: self.doc.arquivo.storage.delete(self.doc.arquivo.name))
        DocumentExtraction.objects.create(document=self.doc, status='review', fields={'valor': 'R$ 5.000,00'})

    def test_documento_escolhido_vira_marcador_e_ia_le_o_texto(self):
        res, call = self.say('Extraia os dados', [tool('ler_documento', {'id': self.doc.pk}), text('Valor: R$ 5.000,00.')],
                             body={'documento_id': self.doc.pk})
        self.assertEqual(res.status_code, 201, res.content)
        user_msg = Message.objects.filter(role='user').get()
        self.assertTrue(user_msg.content.endswith(f'[documento:{self.doc.pk} "Contrato \'Maria\'"]'))
        first = call.call_args_list[0].kwargs
        self.assertIn('ler_documento(id=ID)', first['system'])
        result = call.call_args_list[1].kwargs['messages'][-1]['content']
        self.assertIn('R$ 5.000,00', result)
        self.assertIn('<<<INICIO_DADOS>>>', result)
        self.assertIn('"total_partes": 3', result)                    # texto longo vem em partes

    def test_documento_de_outro_escritorio_ou_sem_acesso(self):
        from cadrius.tests_security import make_org
        other = Document.objects.create(organization=make_org('Outro'), nome='x', arquivo=SimpleUploadedFile('x.txt', b'abc'))
        self.addCleanup(lambda: other.arquivo.storage.delete(other.arquivo.name))
        res, call = self.say('Leia', [text('ok')], body={'documento_id': other.pk})
        self.assertEqual(res.status_code, 404)
        call.assert_not_called()
        res, call = self.say('Leia', [tool('ler_documento', {'id': other.pk}), text('ok')])
        self.assertIn('não encontrado', call.call_args_list[1].kwargs['messages'][-1]['content'])

    def test_continua_a_conversa_com_documento(self):
        res, _ = self.say('Oi', [text('Olá')])
        cid = res.data['id']
        from unittest import mock
        from aigov import llm
        with mock.patch.object(llm, 'call', side_effect=[text('Plano: 1) ...')]) as call:
            r = self.c.post(f'{BASE}conversations/{cid}/', {'mensagem': 'Monte um plano', 'documento_id': self.doc.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn('ler_documento(id=ID)', call.call_args.kwargs['system'])
