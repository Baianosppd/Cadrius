"""CAD-222: assistente com hiperautomação, memória, modo caso, conector MCP e chave de IA do escritório."""
import json
import os
from unittest import mock

from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

from aigov import llm
from assistant.models import AssistantSettings, Conversation, OrgAIKey, PendingAction, PersonalToken
from automations.models import Rule
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact

BASE = '/api/v1/assistant/'
ENV = {'OPENAI_API_KEY': 'o', 'ANTHROPIC_API_KEY': '', 'GEMINI_API_KEY': '', 'GROQ_API_KEY': '', 'MISTRAL_API_KEY': '',
       'MARITACA_API_KEY': '', 'OPENROUTER_API_KEY': '', 'OLLAMA_BASE_URL': '', 'AI_ASSISTANT_PROVIDER_ORDER': ''}
RULE = {'nome': 'Intimação por e-mail vira tarefa', 'gatilho': 'email_received',
        'condicoes': [{'field': 'email.categoria', 'op': 'eq', 'value': 'intimacao'}],
        'acoes': [{'type': 'create_task', 'params': {'titulo': 'Ver {{email.assunto}}', 'prioridade': 'alta', 'quando': 'dias_uteis', 'dias': 0}}]}


def tool(name, args, cid='c1'):
    return llm.Reply('', 'OPENAI', 'm', [llm.ToolCall(cid, name, args)])


def text(t):
    return llm.Reply(t, 'OPENAI', 'm')


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.maria = Contact.objects.create(organization=self.org, name='Maria Cliente', email='maria@c.com', email_consent=True)
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        for p in (mock.patch.dict(os.environ, ENV), mock.patch('billing.credit_weights.credits_for', return_value=0)):
            p.start()
            self.addCleanup(p.stop)

    def say(self, msg, replies, client=None, body=None):
        with mock.patch.object(llm, 'call', side_effect=replies) as call:
            res = (client or self.c).post(f'{BASE}conversations/', {'mensagem': msg, **(body or {})}, format='json')
        return res, call


class HyperautomationTests(Base):
    def test_cria_regra_desligada_com_previa_e_liga_com_simulacao(self):
        res, _ = self.say('crie a automação', [tool('criar_regra', RULE), text('Preparei.')])
        action = res.data['acoes'][0]
        self.assertIn('Nasce DESLIGADA', action['resumo'])
        self.assertIn('E-mail recebido', action['resumo'])
        self.assertFalse(Rule.objects.exists())
        self.c.post(f'{BASE}actions/{action["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        rule = Rule.objects.get()
        self.assertFalse(rule.enabled)
        res, _ = self.say('ligue', [tool('ativar_regra', {'id': rule.pk}), text('Simulei.')])
        act = res.data['acoes'][0]
        self.assertIn('Simulação', act['resumo'])
        self.c.post(f'{BASE}actions/{act["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        rule.refresh_from_db()
        self.assertTrue(rule.enabled)

    def test_regra_invalida_volta_erro_e_membro_nao_cria(self):
        res, call = self.say('x', [tool('criar_regra', {**RULE, 'gatilho': 'nada'}), text('ok')])
        self.assertIn('Regra inválida', call.call_args_list[1].kwargs['messages'][-1]['content'])
        self.assertEqual(PendingAction.objects.count(), 0)
        c = APIClient()
        c.force_authenticate(self.member)
        res, call = self.say('x', [tool('criar_regra', RULE), text('ok')], client=c)
        self.assertIn('Só dono ou administrador', call.call_args_list[1].kwargs['messages'][-1]['content'])

    def test_memoria_entra_no_contexto_e_lembrar_ensina(self):
        from brain import memory
        from brain.models import MemoryItem
        memory.remember(self.org, MemoryItem.Kind.NOTE, 'Prazos trabalhistas: protocolar sempre 2 dias antes.', title='Regra da casa')
        with mock.patch('brain.memory.similar', wraps=memory.similar) as sim:
            res, call = self.say('como tratamos prazos trabalhistas?', [text('Dois dias antes.')])
        sim.assert_called()
        res, _ = self.say('lembre que cliente VIP recebe ligação', [tool('lembrar', {'texto': 'Cliente VIP recebe ligação, não e-mail.'}),
                                                                      text('Preparei.')])
        self.c.post(f'{BASE}actions/{res.data["acoes"][0]["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        self.assertTrue(MemoryItem.objects.filter(title__icontains='Cliente VIP').exists())

    def test_mensagem_ao_cliente_mostra_canal_e_envia_ao_confirmar(self):
        res, _ = self.say('avise a Maria', [tool('enviar_mensagem_cliente', {'contato_id': self.maria.pk, 'mensagem': 'Audiência amanhã.'}),
                                             text('Preparei.')])
        act = res.data['acoes'][0]
        self.assertIn('e-mail', act['resumo'])
        with mock.patch('integrations.email_layout.send', return_value='escritorio') as send:
            out = self.c.post(f'{BASE}actions/{act["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        send.assert_called_once()
        self.assertEqual(out.data['acoes'][0]['status'], 'done')


class CaseModeTests(Base):
    def test_modo_caso_precisa_ser_ligado_e_injeta_o_prompt(self):
        from research.models import MonitoredCase
        case = MonitoredCase.objects.create(organization=self.org, cnj='0001234-56.2030.8.26.0100', tribunal='tjsp', client=self.maria)
        res, _ = self.say('vamos montar', [text('x')], body={'modo': 'caso', 'processo_id': case.pk})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.c.patch(f'{BASE}settings/', {'estrategia_de_caso': True}, format='json').data['estrategia_de_caso'], True)
        res, call = self.say('vamos montar a estratégia', [tool('contexto_do_caso', {'processo_id': case.pk}), text('Fatos…')],
                             body={'modo': 'caso', 'processo_id': case.pk})
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual((res.data['modo'], res.data['processo']), ('caso', case.cnj))
        self.assertIn('ESTRATÉGIA DE CASO', call.call_args_list[0].kwargs['system'])
        self.assertIn('Maria Cliente', call.call_args_list[1].kwargs['messages'][-1]['content'])
        res2, _ = self.say('salve', [tool('salvar_plano_do_caso', {'titulo': 'Plano — alimentos', 'conteudo': '1. Fatos\n[COMPLETAR]'}),
                                     text('ok')])
        self.c.post(f'{BASE}actions/{res2.data["acoes"][0]["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        from minutas.models import Draft
        self.assertEqual(Draft.objects.get().pending, 1)

    def test_membro_nao_liga_configuracao(self):
        c = APIClient()
        c.force_authenticate(self.member)
        self.assertEqual(c.patch(f'{BASE}settings/', {'estrategia_de_caso': True}, format='json').status_code, 403)


class McpTests(Base):
    def token(self, scope='leitura'):
        AssistantSettings.objects.update_or_create(organization=self.org, defaults={'mcp_enabled': True})
        res = self.c.post(f'{BASE}plugins/tokens/', {'nome': 'Claude', 'escopo': scope}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res['Cache-Control'], 'no-store')
        return res.data

    def rpc(self, token, method, params=None, rid=1, in_url=False):
        body = {'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}}
        if in_url:
            return self.client.post(f'/mcp/{token}/', json.dumps(body), content_type='application/json')
        return self.client.post('/mcp/', json.dumps(body), content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_desligado_e_token_invalido(self):
        self.assertEqual(self.c.post(f'{BASE}plugins/tokens/', {'nome': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.rpc('cdr_invalido', 'initialize').status_code, 401)

    def test_fluxo_leitura(self):
        data = self.token()
        raw = data['token']
        self.assertFalse(PersonalToken.objects.filter(token_hash=raw).exists())        # só o hash fica guardado
        init = self.rpc(raw, 'initialize', {'protocolVersion': '2025-06-18'}).json()
        self.assertEqual(init['result']['serverInfo']['name'], 'cadrius')
        self.assertEqual(self.client.post('/mcp/', json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}),
                                          content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {raw}').status_code, 202)
        names = {t['name'] for t in self.rpc(raw, 'tools/list', in_url=True).json()['result']['tools']}
        self.assertIn('buscar_contatos', names)
        self.assertNotIn('criar_tarefa', names)                        # escopo leitura: sem ações
        out = self.rpc(raw, 'tools/call', {'name': 'buscar_contatos', 'arguments': {'termo': 'Maria'}}).json()['result']
        self.assertFalse(out['isError'])
        self.assertIn('Maria Cliente', out['content'][0]['text'])
        denied = self.rpc(raw, 'tools/call', {'name': 'criar_tarefa', 'arguments': {'titulo': 'x', 'data': '2030-01-01'}}).json()['result']
        self.assertTrue(denied['isError'])
        from audit.models import AuditEvent
        self.assertTrue(AuditEvent.objects.filter(action='assistant.mcp_call').exists())

    def test_pedidos_viram_acao_pendente_no_cadrius_e_revogar_corta(self):
        data = self.token('pedidos')
        out = self.rpc(data['token'], 'tools/call', {'name': 'criar_tarefa', 'arguments': {'titulo': 'Ligar Maria', 'data': '2030-01-02'}}).json()
        self.assertIn('aguardando_confirmacao', out['result']['content'][0]['text'])
        conv = Conversation.objects.get(mode='mcp')
        self.assertEqual(conv.actions.get().status, 'pending')
        self.assertIsNotNone(conv.actions.get().message_id)          # aparece como cartão na conversa
        from tasks.models import UserTask
        self.assertFalse(UserTask.objects.exists())
        self.c.delete(f'{BASE}plugins/tokens/{data["id"]}/')
        self.assertEqual(self.rpc(data['token'], 'ping').status_code, 401)

    def test_desligar_conector_revoga_tokens(self):
        data = self.token()
        self.c.patch(f'{BASE}settings/', {'conector_mcp': False}, format='json')
        self.assertEqual(self.rpc(data['token'], 'ping').status_code, 401)


class OwnKeyTests(Base):
    def test_chave_do_escritorio_vem_primeiro_nao_consome_credito_e_nunca_volta(self):
        bad = self.c.post(f'{BASE}plugins/keys/', {'provedor': 'ANTHROPIC', 'chave': 'curta'}, format='json')
        self.assertEqual(bad.status_code, 400)
        ok = self.c.post(f'{BASE}plugins/keys/', {'provedor': 'ANTHROPIC', 'chave': 'sk-ant-chave-do-escritorio-123456'}, format='json')
        self.assertEqual(ok.status_code, 201)
        self.assertNotIn('sk-ant-chave', str(self.c.get(f'{BASE}plugins/').data))
        self.assertEqual(llm.candidates([], sensitive=True, need_tools=True, profile='assistente', org=self.org)[0], 'ANTHROPIC')
        reply = llm.Reply('Oi', 'ANTHROPIC', 'claude', own_key=True)
        with mock.patch('billing.credit_weights.credits_for', return_value=1), \
                mock.patch('billing.credits.check_credit_available', return_value=(True, '')), \
                mock.patch('billing.credits.consume_credit') as consume, mock.patch.object(llm, 'call', return_value=reply) as call:
            self.c.post(f'{BASE}conversations/', {'mensagem': 'oi'}, format='json')
        consume.assert_not_called()
        self.assertEqual(call.call_args.args[0], 'ANTHROPIC')
        self.assertEqual(call.call_args.kwargs['org'], self.org)
        self.assertEqual(OrgAIKey.objects.get().last4, '3456')

    def test_membro_nao_cadastra_e_chave_gratis_que_treina_nao_recebe_dado(self):
        c = APIClient()
        c.force_authenticate(self.member)
        self.assertEqual(c.post(f'{BASE}plugins/keys/', {'provedor': 'OPENAI', 'chave': 'x' * 20}, format='json').status_code, 403)
        self.c.post(f'{BASE}plugins/keys/', {'provedor': 'GEMINI', 'chave': 'g' * 20, 'conta_paga': False}, format='json')
        self.assertNotIn('GEMINI', llm.candidates([], sensitive=True, org=self.org))
        self.assertIn('GEMINI', llm.candidates([], sensitive=False, org=self.org))
