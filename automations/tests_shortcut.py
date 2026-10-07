"""CAD-226: gatilho "Atalho" (relógio, celular, voz) por link secreto."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from automations import catalog, engine
from automations.models import Rule, RuleRun
from cadrius.tests_security import make_org, make_user
from tasks.models import UserTask

RULE = {'name': 'Ligar para o cliente', 'trigger': 'shortcut', 'conditions': [], 'require_approval': True,
        'actions': [{'type': 'create_task', 'params': {'titulo': 'Lembrete: {{atalho.texto}}', 'prioridade': 'alta',
                                                     'quando': 'dias_uteis', 'dias': 0}}]}


def run_now(func, rule_id, refs, dedupe):          # a fila roda na hora no teste
    return engine.execute(rule_id, refs, dedupe)


class ShortcutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.c = APIClient()
        self.c.force_authenticate(self.owner)
        p = mock.patch('core.queue.enqueue', side_effect=run_now)
        p.start()
        self.addCleanup(p.stop)

    def make_rule(self):
        res = self.c.post('/api/v1/automations/rules/', RULE, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        rule = Rule.objects.get(pk=res.json()['id'])
        self.c.post(f'/api/v1/automations/rules/{rule.pk}/simulate/')
        self.c.post(f'/api/v1/automations/rules/{rule.pk}/enable/', {'ativa': True}, format='json')
        return rule

    def test_catalogo_tem_atalho_sem_destinatario(self):
        g = next(x for x in catalog.catalog()['gatilhos'] if x['id'] == 'shortcut')
        self.assertEqual(g['destinatarios'], [])
        bad = {**RULE, 'actions': [{'type': 'send_email', 'params': {'destinatario': 'cliente', 'assunto': 'x', 'mensagem': 'y'}}]}
        self.assertEqual(self.c.post('/api/v1/automations/rules/', bad, format='json').status_code, 400)

    def test_link_dispara_a_regra_e_cria_tarefa_para_quem_criou(self):
        rule = self.make_rule()
        res = self.c.post(f'/api/v1/automations/rules/{rule.pk}/atalho/')
        url = res.json()['url']
        rule.refresh_from_db()
        self.assertTrue(rule.shortcut_key_hash)
        self.assertNotIn(url.rsplit('/', 2)[-2], rule.shortcut_key_hash)                    # só o hash fica no banco
        path = url[url.index('/api/'):]
        out = APIClient().post(path, {'texto': 'Maria sobre a audiência', 'origem': 'relógio'}, format='json')
        self.assertEqual(out.status_code, 200, out.content)
        self.assertEqual(out.json()['mensagem'], 'Feito: Ligar para o cliente.')
        task = UserTask.objects.get()
        self.assertEqual(task.titulo, 'Lembrete: Maria sobre a audiência')
        self.assertEqual(task.responsavel, self.owner)
        self.assertEqual(RuleRun.objects.get().status, 'success')
        self.assertTrue(self.c.get(f'/api/v1/automations/rules/{rule.pk}/').json()['atalho_configurado'])

    def test_chave_errada_trocada_desligada_e_limite(self):
        rule = self.make_rule()
        old = self.c.post(f'/api/v1/automations/rules/{rule.pk}/atalho/').json()['url']
        new = self.c.post(f'/api/v1/automations/rules/{rule.pk}/atalho/').json()['url']
        anon = APIClient()
        self.assertEqual(anon.post(old[old.index('/api/'):], {}, format='json').status_code, 404)        # a antiga morreu
        self.assertEqual(anon.post(f'/api/v1/publico/atalho/{rule.pk}/errada/', {}, format='json').status_code, 404)
        path = new[new.index('/api/'):]
        codes = [anon.post(path, {}, format='json').status_code for _ in range(7)]
        self.assertEqual(codes[:6], [200] * 6)
        self.assertEqual(codes[6], 429)
        Rule.objects.filter(pk=rule.pk).update(enabled=False)
        cache.clear()
        self.assertEqual(anon.post(path, {}, format='json').status_code, 409)

    def test_so_gestor_gera_link_e_so_para_atalho(self):
        rule = self.make_rule()
        member = APIClient()
        member.force_authenticate(self.member)
        self.assertEqual(member.post(f'/api/v1/automations/rules/{rule.pk}/atalho/').status_code, 403)
        other = Rule.objects.create(organization=self.org, name='Outra', trigger='case_movement')
        self.assertEqual(self.c.post(f'/api/v1/automations/rules/{other.pk}/atalho/').status_code, 400)

    def test_simulacao_usa_exemplo(self):
        rule = self.make_rule()
        sim = self.c.post(f'/api/v1/automations/rules/{rule.pk}/simulate/').json()
        self.assertEqual(sim['origem'], 'exemplo')
        self.assertIn('Ligar para a Maria', sim['passos'][0]['detalhe'])
