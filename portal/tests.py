from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from carteira.models import Receivable
from contacts.models import Contact
from portal.models import PortalLink
from portal.plain import FALLBACK, explain
from research.models import CaseMovement, MonitoredCase


class PlainTests(APITestCase):
    def test_traducoes(self):
        self.assertEqual(explain('Conclusos para decisão')[0], 'O processo está com o juiz para analisar e decidir.')
        self.assertIn('definitiva', explain('Trânsito em julgado')[0])
        self.assertIn('contra o pedido', explain('Julgado improcedente o pedido')[0])
        self.assertIn('aceitou o pedido', explain('Procedência')[0])
        self.assertIn('parte do pedido', explain('Procedência em Parte')[0])
        self.assertEqual(explain('Código 99999 estranho'), (FALLBACK, False))


class PortalTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.viewer = make_user('v@x.com', self.org, role='VIEWER')
        self.cli = Contact.objects.create(organization=self.org, name='Maria Cliente', email='maria@c.com', email_consent=True)
        self.other = Contact.objects.create(organization=self.org, name='João Outro')
        self.case = MonitoredCase.objects.create(organization=self.org, cnj='0000832-35.2018.4.01.3202', tribunal='trf1', client=self.cli,
                                                 label='Apelido interno sigiloso')
        CaseMovement.objects.create(case=self.case, name='Conclusos para decisão', digest='a', occurred_at=timezone.now())
        MonitoredCase.objects.create(organization=self.org, cnj='0000001-00.2020.8.26.0100', tribunal='tjsp', client=self.other)
        Receivable.objects.create(organization=self.org, contact=self.cli, description='Parcela 1/2', amount_cents=50000,
                                  due_date=timezone.localdate(), payment_url='https://asaas.com/i/1')
        Receivable.objects.create(organization=self.org, contact=self.other, description='De outro', amount_cents=1, due_date=timezone.localdate())
        self.c = APIClient()
        self.c.force_authenticate(self.owner)

    def create(self, **kw):
        return self.c.post('/api/v1/portal/links/', {'contato_id': self.cli.pk, **kw}, format='json')

    def test_cliente_ve_so_o_que_e_dele(self):
        res = self.create(enviar_email=True)
        self.assertEqual(res.status_code, 201, res.content)
        url = res.json()['url']
        token = url.rsplit('/', 1)[-1]
        self.assertEqual(res.json()['envio'], 'email')
        self.assertIn(url, mail.outbox[0].body)
        self.assertFalse(PortalLink.objects.filter(token_hash=token).exists())          # só o hash fica guardado
        pub = APIClient()
        data = pub.get(f'/api/v1/portal/acesso/{token}/').json()
        self.assertEqual((data['cliente'], len(data['processos'])), ('Maria', 1))
        self.assertEqual(data['processos'][0]['andamentos'][0]['explicacao'], 'O processo está com o juiz para analisar e decidir.')
        self.assertNotIn('sigiloso', str(data))
        self.assertEqual([h['descricao'] for h in data['honorarios']], ['Parcela 1/2'])
        pub.get(f'/api/v1/portal/acesso/{token}/')
        link = PortalLink.objects.get()
        self.assertEqual(link.access_count, 2)
        self.assertEqual(AuditEvent.objects.filter(action='portal.viewed').count(), 1)      # 1 por hora
        self.assertEqual(self.c.post(f'/api/v1/portal/links/{link.pk}/revogar/').json()['situacao'], 'revogado')
        self.assertEqual(pub.get(f'/api/v1/portal/acesso/{token}/').status_code, 404)

    def test_regras_de_criacao_expiracao_e_permissoes(self):
        self.assertEqual(self.c.post('/api/v1/portal/links/', {'contato_id': Contact.objects.create(
            organization=self.org, name='Perito', kind='perito').pk}, format='json').status_code, 400)
        self.assertEqual(self.create(dias=999).status_code, 400)
        token = self.create(mostrar_financeiro=False).json()['url'].rsplit('/', 1)[-1]
        self.assertNotIn('honorarios', APIClient().get(f'/api/v1/portal/acesso/{token}/').json())
        self.create()
        self.create()
        self.assertEqual(self.create().status_code, 400)                                   # máximo 3 ativos
        PortalLink.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(APIClient().get(f'/api/v1/portal/acesso/{token}/').status_code, 404)
        self.assertEqual(APIClient().get('/api/v1/portal/acesso/curto/').status_code, 404)
        v = APIClient()
        v.force_authenticate(self.viewer)
        self.assertEqual(v.post('/api/v1/portal/links/', {'contato_id': self.cli.pk}, format='json').status_code, 403)
        outro = APIClient()
        outro.force_authenticate(make_user('o@y.com', make_org('Y'), role='OWNER'))
        self.assertEqual(outro.post('/api/v1/portal/links/', {'contato_id': self.cli.pk}, format='json').status_code, 404)
        self.assertEqual(outro.get('/api/v1/portal/links/').json(), [])

    def test_sem_consentimento_nao_envia(self):
        self.cli.email_consent = False
        self.cli.save()
        with mock.patch('integrations.services.send_office_email') as send:
            self.assertEqual(self.create(enviar_email=True).json()['envio'], 'sem_consentimento')
        send.assert_not_called()
