"""Camada única de IA (CAD-221): roteamento por política e sigilo, catálogo sem segredo e conversão de mensagens."""
import os
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from aigov import llm

KEYS = {'ANTHROPIC_API_KEY': 'a', 'OPENAI_API_KEY': 'o', 'GEMINI_API_KEY': 'g', 'GROQ_API_KEY': 'q',
        'MISTRAL_API_KEY': 'm', 'MARITACA_API_KEY': 's', 'OPENROUTER_API_KEY': 'r', 'OLLAMA_BASE_URL': 'http://ollama:11434/v1'}
CLEAN = {k: '' for k in [*KEYS, 'GEMINI_PAID', 'MISTRAL_PAID', 'OPENROUTER_PAID', 'AI_PROVIDER_ORDER',
                         'AI_ASSISTANT_PROVIDER_ORDER', 'OPENROUTER_MODEL']}


class RoutingTests(TestCase):          # CAD-224: a ordem vem da cadeia da atividade (tabela AIRoute)
    def setUp(self):
        cache.clear()

    def test_dado_sigiloso_nunca_vai_para_plano_gratuito_que_treina(self):
        with mock.patch.dict(os.environ, {**CLEAN, **KEYS}):
            sigiloso = llm.candidates(None, sensitive=True)
            aberto = llm.candidates(None, sensitive=False)
        for treina in ('GEMINI', 'MISTRAL', 'OPENROUTER'):
            self.assertNotIn(treina, sigiloso)
            self.assertIn(treina, aberto)
        self.assertIn('GROQ', sigiloso)          # Groq não treina com os dados
        self.assertIn('OLLAMA', sigiloso)        # local: o dado não sai do servidor

    def test_conta_paga_libera_o_provedor_para_dado_sigiloso(self):
        with mock.patch.dict(os.environ, {**CLEAN, **KEYS, 'GEMINI_PAID': 'true', 'OPENROUTER_MODEL': 'anthropic/claude-x'}):
            sigiloso = llm.candidates(None, sensitive=True)
        self.assertIn('GEMINI', sigiloso)
        self.assertIn('OPENROUTER', sigiloso)    # modelo sem ":free" é pago
        self.assertNotIn('MISTRAL', sigiloso)

    def test_ordem_por_perfil_politica_e_override(self):
        with mock.patch.dict(os.environ, {**CLEAN, **KEYS}):
            self.assertEqual(llm.candidates(None)[0], 'OPENAI')                        # perfil antigo "economico" = leitura
            self.assertEqual(llm.candidates(None, profile='assistente')[0], 'ANTHROPIC')
            self.assertEqual(llm.candidates(None, profile='redacao')[0], 'MARITACA')
            self.assertEqual(llm.candidates(['OPENAI', 'OLLAMA'], profile='assistente'), ['OPENAI', 'OLLAMA'])
            # a Gestão troca a cadeia e desliga as reservas
            from aigov import routing
            from aigov.models import AIRoute
            AIRoute.objects.create(activity='automacao', providers=['MARITACA', 'OPENAI'], use_reserves=False)
            routing.invalidate()
            self.assertEqual(llm.candidates(None, profile='assistente'), ['MARITACA', 'OPENAI'])

    def test_sem_chave_nao_e_candidato_e_catalogo_nao_expoe_segredo(self):
        with mock.patch.dict(os.environ, {**CLEAN, 'OPENAI_API_KEY': 'sk-segredo-123'}):
            self.assertEqual(llm.candidates(None), ['OPENAI'])
            rows = llm.catalog(['OPENAI'])
        self.assertNotIn('sk-segredo-123', str(rows))
        openai = next(r for r in rows if r['chave'] == 'OPENAI')
        self.assertTrue(openai['configurado'] and openai['permitido'])
        self.assertFalse(next(r for r in rows if r['chave'] == 'ANTHROPIC')['permitido'])

    def test_fallback_passa_ao_proximo_e_erro_final_e_seguro(self):
        ok = llm.Reply('oi', 'OPENAI', 'm')
        with mock.patch.object(llm, 'call', side_effect=[RuntimeError('boom'), ok]) as call:
            self.assertEqual(llm.chat_with_fallback(['ANTHROPIC', 'OPENAI'], system='s', messages=[]).provider, 'OPENAI')
        self.assertEqual(call.call_count, 2)
        with mock.patch.object(llm, 'call', side_effect=RuntimeError('chave sk-xyz inválida')):
            with self.assertRaises(llm.LLMError) as ctx:
                llm.chat_with_fallback(['OPENAI'], system='s', messages=[])
        self.assertNotIn('sk-xyz', str(ctx.exception))
        with self.assertRaises(llm.LLMError):
            llm.chat_with_fallback([], system='s', messages=[])


class MessageFormatTests(SimpleTestCase):
    def history(self, provider='OPENAI', raw=None):
        call = llm.ToolCall('t1', 'buscar_contatos', {'termo': 'Maria'})
        return [{'role': 'user', 'content': 'ache a Maria'},
                {'role': 'assistant', 'content': '', 'tool_calls': [call], 'provider': provider, 'raw': raw},
                {'role': 'tool', 'tool_call_id': 't1', 'name': 'buscar_contatos', 'content': '[{"nome": "Maria"}]'},
                {'role': 'tool', 'tool_call_id': 't2', 'name': 'x', 'content': '{}'}]

    def test_formato_openai(self):
        out = llm._to_openai('sistema', self.history())
        self.assertEqual(out[0], {'role': 'system', 'content': 'sistema'})
        self.assertEqual(out[2]['tool_calls'][0]['function']['name'], 'buscar_contatos')
        self.assertEqual(out[3], {'role': 'tool', 'tool_call_id': 't1', 'content': '[{"nome": "Maria"}]'})

    def test_formato_claude_agrupa_resultados_e_reenvia_conteudo_original(self):
        out = llm._to_anthropic(self.history())
        self.assertEqual(out[1]['content'][0], {'type': 'tool_use', 'id': 't1', 'name': 'buscar_contatos', 'input': {'termo': 'Maria'}})
        self.assertEqual(len(out), 3)                       # os dois resultados numa única mensagem do usuário
        self.assertEqual([b['tool_use_id'] for b in out[2]['content']], ['t1', 't2'])
        raw = [SimpleNamespace(type='text')]
        self.assertIs(llm._to_anthropic(self.history('ANTHROPIC', raw))[1]['content'], raw)

    def test_chamada_openai_compativel_monta_ferramentas_e_le_resposta(self):
        fn = SimpleNamespace(name='buscar_contatos', arguments='{"termo": "Ana"}')
        msg = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id='c1', function=fn)])
        client = mock.MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
        tool = {'name': 'buscar_contatos', 'description': 'd', 'parameters': {'type': 'object', 'properties': {}}}
        with mock.patch.dict(os.environ, {**CLEAN, 'GROQ_API_KEY': 'q'}), mock.patch.object(llm, '_openai_client', return_value=client):
            reply = llm.call('GROQ', system='s', messages=[{'role': 'user', 'content': 'oi'}], tools=[tool])
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'llama-3.3-70b-versatile')
        self.assertEqual(kwargs['tools'][0]['function']['name'], 'buscar_contatos')
        self.assertEqual(reply.tool_calls[0].arguments, {'termo': 'Ana'})

    def test_extrator_usa_a_camada_para_provedores_novos(self):
        from extraction import ai_wrapper
        from extraction.schemas import ServiceOrderSchema
        payload = ('{"document_type": "SERVICE_ORDER", "confidence_score": 90, "customer_name": "X", '
                   '"service_description": "Y", "priority": "LOW", "target_sla_days": 1, "contact_phone": "1"}')
        with mock.patch.object(llm, 'complete_json', return_value=payload) as cj:
            out = ai_wrapper.extract_fields_from_text('texto', ServiceOrderSchema, 'extraia', provider='MARITACA')
        self.assertEqual(out['customer_name'], 'X')
        self.assertEqual(cj.call_args.args[0], 'MARITACA')
