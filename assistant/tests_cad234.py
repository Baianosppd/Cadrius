"""CAD-234: o assistente cadastra o contato no mesmo pedido da automação/mensagem; regras com contato fixo."""
from unittest import mock

from assistant.models import PendingAction
from assistant.tests_h import BASE, Base, text, tool
from automations import catalog
from automations.models import Rule
from contacts.models import Contact
from contacts.quick import find_existing

NOVO = {'nome': 'João Contador', 'email': 'joao@contab.com', 'telefone': '(11) 98888-7777', 'autoriza_email': True}
MENSAL = {'nome': 'Lembrete mensal ao contador', 'gatilho': 'monthly_goal', 'configuracao': {'dia': 5},
          'acoes': [{'type': 'send_message', 'params': {'destinatario': 'novo_contato', 'canal': 'email', 'assunto': 'Fechamento',
                                                         'mensagem': 'Olá, {{destinatario.primeiro_nome}}! Segue o fechamento.'}}]}


class NovoContatoNaRegraTests(Base):
    def test_uma_confirmacao_cadastra_contato_e_cria_regra_com_contato_fixo(self):
        res, _ = self.say('avise o contador todo mês', [tool('criar_regra', {**MENSAL, 'novo_contato': NOVO}), text('Preparei.')])
        action = res.data['acoes'][0]
        self.assertIn('cadastra o contato "João Contador"', action['resumo'])
        self.assertIn('autorizou e-mail', action['resumo'])
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 1)          # nada antes da confirmação
        self.c.post(f'{BASE}actions/{action["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        joao = find_existing(self.org, {'email': 'joao@contab.com'})
        self.assertTrue(joao.email_consent)
        self.assertFalse(joao.whatsapp_consent)
        self.assertIn('dono@x.com', joao.consent_source)
        rule = Rule.objects.get()
        self.assertEqual(rule.actions[0]['params']['destinatario'], f'contato:{joao.pk}')
        self.assertFalse(rule.enabled)

    def test_reaproveita_contato_existente_pelo_email(self):
        novo = {'nome': 'Maria C.', 'email': 'maria@c.com'}
        res, _ = self.say('x', [tool('criar_regra', {**MENSAL, 'novo_contato': novo}), text('ok')])
        self.assertIn('usa o contato já cadastrado "Maria Cliente"', res.data['acoes'][0]['resumo'])
        self.c.post(f'{BASE}actions/{res.data["acoes"][0]["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        self.assertEqual(Contact.objects.filter(organization=self.org).count(), 1)
        self.assertEqual(Rule.objects.get().actions[0]['params']['destinatario'], f'contato:{self.maria.pk}')

    def test_sem_novo_contato_o_pedido_volta_com_erro(self):
        res, call = self.say('x', [tool('criar_regra', MENSAL), text('ok')])
        self.assertIn('informe novo_contato', call.call_args_list[1].kwargs['messages'][-1]['content'])
        self.assertEqual(PendingAction.objects.count(), 0)

    def test_mensagem_para_quem_nao_e_contato(self):
        args = {'mensagem': 'Olá! Recebemos seus documentos.', 'canal': 'email', 'assunto': 'Documentos',
                'novo_contato': {'nome': 'Pedro Novo', 'email': 'pedro@n.com', 'autoriza_email': True}}
        res, _ = self.say('mande um e-mail ao Pedro', [tool('enviar_mensagem_cliente', args), text('Preparei.')])
        action = res.data['acoes'][0]
        self.assertIn('cadastra o contato "Pedro Novo"', action['resumo'])
        self.assertIn('Depois envia por e-mail', action['resumo'])
        with mock.patch('automations.messaging.deliver', return_value='email') as deliver:
            self.c.post(f'{BASE}actions/{action["id"]}/decide/', {'decisao': 'confirmar'}, format='json')
        pedro = find_existing(self.org, {'email': 'pedro@n.com'})
        self.assertTrue(pedro.email_consent)
        self.assertEqual(deliver.call_args.args[1], pedro)

    def test_sem_autorizacao_o_cartao_avisa(self):
        args = {'mensagem': 'Oi', 'canal': 'whatsapp', 'novo_contato': {'nome': 'Ana', 'telefone': '11999998888'}}
        res, _ = self.say('x', [tool('enviar_mensagem_cliente', args), text('ok')])
        self.assertIn('falta a autorização', res.data['acoes'][0]['resumo'])


class ContatoFixoNaRegraTests(Base):
    def test_catalogo_aceita_contato_fixo_em_qualquer_gatilho(self):
        body = catalog.clean_rule({'name': 'Mensal', 'trigger': 'monthly_goal', 'trigger_config': {'dia': 5},
                                   'actions': [{'type': 'send_email', 'params': {'destinatario': f'contato:{self.maria.pk}',
                                                                                 'assunto': 'Oi', 'mensagem': 'Oi'}}]})
        self.assertEqual(body['actions'][0]['params']['destinatario'], f'contato:{self.maria.pk}')
        with self.assertRaises(catalog.RuleError):
            catalog.clean_rule({'name': 'Mensal', 'trigger': 'monthly_goal', 'trigger_config': {'dia': 5},
                                'actions': [{'type': 'send_email', 'params': {'destinatario': 'contato:abc', 'assunto': 'Oi',
                                                                              'mensagem': 'Oi'}}]})

    def test_simulacao_usa_o_contato_fixo_e_o_nome_dele(self):
        from automations import engine
        rule = Rule.objects.create(organization=self.org, created_by=self.owner, name='Mensal', trigger='monthly_goal',
                                   trigger_config={'dia': 5}, enabled=False,
                                   actions=[{'type': 'send_message', 'params': {'destinatario': f'contato:{self.maria.pk}', 'canal': 'email',
                                                                                'assunto': 'Oi', 'mensagem': 'Oi {{destinatario.primeiro_nome}}'}}])
        out = engine.simulate(rule)
        step = out['passos'][-1] if 'passos' in out else out['steps'][-1]
        self.assertEqual(step['dados']['contato_id'], self.maria.pk)
        self.assertEqual(step['dados']['mensagem'], 'Oi Maria')
