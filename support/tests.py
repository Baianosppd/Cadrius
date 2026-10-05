from django.contrib.auth.models import Group
from django.core.cache import cache
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from notifications.models import Notification
from support.models import Ticket


class SupportTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.staff = make_user('suporte@cadrius.ia.br')
        self.staff.is_staff = True
        self.staff.save()
        self.staff.groups.add(Group.objects.get_or_create(name='Cadrius Suporte')[0])

    def client_for(self, user, mfa=False):
        c = APIClient()
        c.force_authenticate(user, token={'amr': 'mfa'} if mfa else None)
        return c

    def open(self, user=None, **kw):
        body = {'subject': 'Não consigo importar', 'body': 'A planilha dá erro na linha 3.', 'category': 'problema',
                'priority': 'urgente', 'page_url': '/importar', **kw}
        return self.client_for(user or self.member).post('/api/v1/support/tickets/', body, format='json')

    def test_abrir_conversar_e_ver_so_o_proprio(self):
        res = self.open()
        self.assertEqual(res.status_code, 201, res.content)
        t = res.json()
        self.assertEqual((t['priority'], t['status']), ('normal', 'aberto'))       # cliente não marca urgente
        other_member = make_user('outro@x.com', self.org, role='MEMBER')
        self.assertEqual(self.client_for(other_member).get(f"/api/v1/support/tickets/{t['id']}/").status_code, 404)
        self.assertEqual(len(self.client_for(self.owner).get('/api/v1/support/tickets/').json()), 1)   # dono vê todos
        self.assertEqual(self.open(subject='oi').status_code, 400)

    def test_equipe_responde_nota_interna_e_cliente_e_avisado(self):
        tid = self.open().json()['id']
        staff = self.client_for(self.staff, mfa=True)
        self.assertEqual(self.client_for(self.staff).get('/api/v1/backoffice/support/tickets/').status_code, 403)   # sem MFA
        queue = staff.get('/api/v1/backoffice/support/tickets/?status=ativos').json()
        self.assertEqual((queue['total'], queue['metricas']['sem_resposta']), (1, 1))
        staff.post(f'/api/v1/backoffice/support/tickets/{tid}/', {'body': 'Cliente parece usar CSV com vírgula.', 'internal': True}, format='json')
        res = staff.post(f'/api/v1/backoffice/support/tickets/{tid}/', {'body': 'Pode enviar a planilha de novo?'}, format='json').json()
        self.assertEqual((res['status'], res['assigned_to']), ('aguardando_cliente', 'suporte@cadrius.ia.br'))
        mine = self.client_for(self.member).get(f'/api/v1/support/tickets/{tid}/').json()
        self.assertEqual([m['body'] for m in mine['messages']], ['A planilha dá erro na linha 3.', 'Pode enviar a planilha de novo?'])
        self.assertEqual(mine['messages'][1]['author'], 'Equipe Cadrius')
        self.assertTrue(Notification.objects.filter(user=self.member, type='suporte').exists())
        back = self.client_for(self.member).post(f'/api/v1/support/tickets/{tid}/messages/', {'body': 'Enviei de novo, obrigado.'}, format='json')
        self.assertEqual(back.json()['status'], 'aberto')
        self.assertIsNotNone(Ticket.objects.get(pk=tid).first_response_at)

    def test_status_prioridade_fechar_e_reabrir(self):
        tid = self.open().json()['id']
        staff = self.client_for(self.staff, mfa=True)
        self.assertEqual(staff.patch(f'/api/v1/backoffice/support/tickets/{tid}/', {'priority': 'urgente', 'assign': 'me'}, format='json').json()['priority'], 'urgente')
        self.assertEqual(staff.patch(f'/api/v1/backoffice/support/tickets/{tid}/', {'status': 'xpto'}, format='json').status_code, 400)
        me = self.client_for(self.member)
        self.assertEqual(me.post(f'/api/v1/support/tickets/{tid}/status/', {'action': 'close'}, format='json').json()['status'], 'fechado')
        self.assertEqual(me.post(f'/api/v1/support/tickets/{tid}/messages/', {'body': 'mais uma coisa'}, format='json').status_code, 400)
        self.assertEqual(me.post(f'/api/v1/support/tickets/{tid}/status/', {'action': 'reopen'}, format='json').json()['status'], 'aberto')

    def test_acesso_assistido_temporario(self):
        tid = self.open().json()['id']
        me = self.client_for(self.member)
        self.assertEqual(me.post(f'/api/v1/support/tickets/{tid}/access/', {'hours': 5}, format='json').status_code, 400)
        self.assertIsNotNone(me.post(f'/api/v1/support/tickets/{tid}/access/', {'hours': 24}, format='json').json()['access_until'])
        staff = self.client_for(self.staff, mfa=True)
        self.assertIsNotNone(staff.get(f'/api/v1/backoffice/support/tickets/{tid}/').json()['access_until'])
        self.assertIsNone(me.delete(f'/api/v1/support/tickets/{tid}/access/').json()['access_until'])
        self.assertTrue(AuditEvent.objects.filter(action='support.access_granted').exists())
        self.assertTrue(AuditEvent.objects.filter(action='support.access_revoked').exists())
