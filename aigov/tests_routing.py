"""CAD-224: IA por atividade (cadeia configurável na Gestão) com reserva automática e disjuntor de saúde."""
import os
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from aigov import llm, routing
from aigov.models import AIRoute

KEYS = {'ANTHROPIC_API_KEY': 'a', 'OPENAI_API_KEY': 'o', 'GROQ_API_KEY': 'g', 'MARITACA_API_KEY': 'm', 'GEMINI_API_KEY': 'ge',
        'GEMINI_PAID': 'true'}


class RoutingTests(TestCase):
    def setUp(self):
        cache.clear()
        env = mock.patch.dict(os.environ, KEYS)
        env.start()
        self.addCleanup(env.stop)

    def test_recomendacao_por_atividade(self):
        self.assertEqual(llm.candidates(None, profile='automacao')[0], 'ANTHROPIC')
        self.assertEqual(llm.candidates(None, profile='redacao')[0], 'MARITACA')
        self.assertEqual(llm.candidates(None, profile='triagem')[0], 'GROQ')
        self.assertEqual(llm.candidates(None, profile='extracao')[0], 'OPENAI')
        self.assertEqual(llm.candidates(None, profile='assistente')[0], 'ANTHROPIC')        # perfil antigo → automacao

    def test_gestao_troca_a_cadeia_e_reservas(self):
        AIRoute.objects.create(activity='redacao', providers=['OPENAI'], use_reserves=False)
        routing.invalidate()
        self.assertEqual(llm.candidates(None, profile='redacao'), ['OPENAI'])
        AIRoute.objects.filter(activity='redacao').update(use_reserves=True)
        routing.invalidate()
        chain = llm.candidates(None, profile='redacao')
        self.assertEqual(chain[0], 'OPENAI')
        self.assertGreater(len(chain), 1)

    def test_provedor_que_cai_vai_para_o_fim_e_volta(self):
        for _ in range(routing.FAIL_LIMIT):
            routing.record('ANTHROPIC', False, 'APIConnectionError')
        chain = llm.candidates(None, profile='automacao')
        self.assertEqual(chain[0], 'OPENAI')
        self.assertEqual(chain[-1], 'ANTHROPIC')
        cache.delete('aigov:health:ANTHROPIC:open')
        routing.record('ANTHROPIC', True)
        self.assertEqual(llm.candidates(None, profile='automacao')[0], 'ANTHROPIC')

    def test_sigilo_continua_mesmo_na_cadeia(self):
        with mock.patch.dict(os.environ, {'GEMINI_PAID': ''}):
            self.assertNotIn('GEMINI', llm.candidates(None, sensitive=True, profile='marketing'))
            self.assertEqual(llm.candidates(None, sensitive=False, profile='marketing')[0], 'GEMINI')

    def test_chat_cai_e_o_proximo_assume(self):
        ok = llm.Reply(text='oi', provider='OPENAI', model='m')
        calls = []

        def fake(p, *a, **k):
            calls.append(p.key)
            if p.key == 'ANTHROPIC':
                raise RuntimeError('fora do ar')
            return ok
        with mock.patch.object(llm, '_call_anthropic', side_effect=fake), mock.patch.object(llm, '_call_openai_compat', side_effect=fake):
            reply = llm.chat_with_fallback(llm.candidates(None, profile='automacao'), system='s', messages=[{'role': 'user', 'content': 'x'}])
        self.assertEqual(reply.text, 'oi')
        self.assertEqual(calls[:2], ['ANTHROPIC', 'OPENAI'])
        self.assertEqual(routing.health('ANTHROPIC')['falhas'], 1)

    def test_extracao_passa_para_o_proximo_provedor(self):
        from pydantic import BaseModel

        from extraction import ai_wrapper

        class S(BaseModel):
            nome: str
        seq = []

        def fake(provider, system, user):
            seq.append(provider)
            if provider == 'OPENAI':
                raise RuntimeError('chave inválida')
            return '{"nome": "Maria"}'
        with mock.patch.object(ai_wrapper, '_call', side_effect=fake):
            out = ai_wrapper.extract_fields_from_text('texto', S, 'p', provider='OPENAI', fallbacks=['GEMINI'])
        self.assertEqual(out, {'nome': 'Maria'})
        self.assertEqual(seq, ['OPENAI', 'GEMINI'])


class StaffRoutesApiTests(TestCase):
    def setUp(self):
        cache.clear()
        from django.contrib.auth import get_user_model
        self.ti = get_user_model().objects.create_user(username='ti@cadrius.com', email='ti@cadrius.com', password='x-Str0ng-Pass!',
                                                       is_staff=True, is_superuser=True)
        self.c = APIClient()
        self.c.force_authenticate(self.ti)
        p = mock.patch('accounts.mfa.staff_session_ok', return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_lista_troca_e_restaura(self):
        data = self.c.get('/api/v1/backoffice/ia/rotas/').json()
        auto = next(a for a in data['atividades'] if a['atividade'] == 'automacao')
        self.assertEqual(auto['cadeia'][0], 'ANTHROPIC')
        self.assertIn('saude', data['provedores'][0])
        bad = self.c.patch('/api/v1/backoffice/ia/rotas/automacao/', {'cadeia': ['XPTO']}, format='json')
        self.assertEqual(bad.status_code, 400)
        ok = self.c.patch('/api/v1/backoffice/ia/rotas/redacao/', {'cadeia': ['anthropic', 'maritaca'], 'usar_reservas': False}, format='json')
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual((ok.data['cadeia'], ok.data['usar_reservas'], ok.data['personalizado']), (['ANTHROPIC', 'MARITACA'], False, True))
        from audit.models import AuditEvent
        self.assertTrue(AuditEvent.objects.filter(action='ai.route_changed').exists())
        back = self.c.delete('/api/v1/backoffice/ia/rotas/redacao/')
        self.assertEqual(back.data['cadeia'][0], 'MARITACA')
        self.assertFalse(back.data['personalizado'])
