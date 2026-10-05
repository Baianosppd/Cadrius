from django.core.cache import cache
from django.db import connection
from rest_framework.test import APIClient, APITestCase

from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user
from contacts.models import Contact
from contacts.validation import clean_contact

CPF = '529.982.247-25'
CNPJ = '11.222.333/0001-81'


class ValidationTests(APITestCase):
    def test_normaliza_e_valida(self):
        values, errors = clean_contact({'name': '  Ana   Souza ', 'document': '52998224725', 'email': 'ANA@X.COM',
                                        'phone': '+55 (11) 98888-7777', 'kind': 'Réu', 'tags': 'vip; trabalhista,vip'})
        self.assertEqual(errors, [])
        self.assertEqual((values['name'], values['document'], values['person_type']), ('Ana Souza', CPF, 'PF'))
        self.assertEqual((values['email'], values['phone'], values['kind']), ('ana@x.com', '11988887777', 'parte_contraria'))
        self.assertEqual(values['tags'], ['trabalhista', 'vip'])
        self.assertEqual(clean_contact({'name': 'Empresa', 'document': CNPJ})[0]['person_type'], 'PJ')
        _, errors = clean_contact({'name': 'X', 'document': '111', 'email': 'nao', 'phone': '123', 'kind': 'astronauta'})
        self.assertEqual(len(errors), 5)


class ContactApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('adv@x.com', self.org, role='MEMBER')
        self.viewer = make_user('ver@x.com', self.org, role='VIEWER')
        self.c = APIClient()
        self.c.force_authenticate(self.member)

    def create(self, **kw):
        body = {'name': 'Maria Clara Souza', 'document': CPF, 'email': 'maria@x.com', 'phone': '11988887777', **kw}
        return self.c.post('/api/v1/contacts/', body, format='json')

    def test_cria_cifrado_e_busca_por_nome_documento_email_telefone(self):
        res = self.create(whatsapp_consent=True)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(res.json()['can_whatsapp'])
        self.assertFalse(res.json()['can_email'])
        with connection.cursor() as cur:
            cur.execute('SELECT name, document, email, phone FROM contacts_contact')
            self.assertTrue(all(v.startswith('enc::') for v in cur.fetchone()))
        for q in ('clara', 'souz', '529.982.247-25', 'maria@x.com', '(11) 98888-7777'):
            self.assertEqual(self.c.get('/api/v1/contacts/', {'q': q}).json()['total'], 1, q)
        self.assertEqual(self.c.get('/api/v1/contacts/', {'q': 'pedro'}).json()['total'], 0)
        self.assertEqual(self.create().status_code, 409)                           # mesmo CPF no escritório
        sem_doc = self.c.post('/api/v1/contacts/', {'name': 'Outra Maria', 'email': 'MARIA@x.com'}, format='json')
        self.assertEqual(sem_doc.status_code, 409)                                 # mesmo e-mail = provável repetido
        self.assertIn('e-mail', sem_doc.json()['detail'])
        self.assertTrue(AuditEvent.objects.filter(action='contact.created').exists())

    def test_isolamento_entre_escritorios_e_mesmo_cpf_em_outro(self):
        cid = self.create().json()['id']
        other = APIClient()
        other.force_authenticate(make_user('b@b.com', make_org(), role='OWNER'))
        self.assertEqual(other.get(f'/api/v1/contacts/{cid}/').status_code, 404)
        self.assertEqual(other.get('/api/v1/contacts/').json()['total'], 0)
        self.assertEqual(other.post('/api/v1/contacts/', {'name': 'Maria', 'document': CPF}, format='json').status_code, 201)

    def test_consentimento_opt_out_e_papeis(self):
        cid = self.create().json()['id']
        res = self.c.patch(f'/api/v1/contacts/{cid}/', {'email_consent': True, 'consent_source': 'termo assinado em 01/10'}, format='json').json()
        self.assertTrue(res['can_email'])
        self.assertEqual(res['consent_source'], 'termo assinado em 01/10')
        self.assertFalse(self.c.patch(f'/api/v1/contacts/{cid}/', {'opted_out': True}, format='json').json()['can_email'])
        viewer = APIClient()
        viewer.force_authenticate(self.viewer)
        self.assertEqual(viewer.get('/api/v1/contacts/').status_code, 200)
        self.assertEqual(viewer.post('/api/v1/contacts/', {'name': 'X Y'}, format='json').status_code, 403)
        self.assertEqual(self.c.delete(f'/api/v1/contacts/{cid}/').status_code, 403)          # membro não exclui
        owner = APIClient()
        owner.force_authenticate(self.owner)
        self.assertEqual(owner.delete(f'/api/v1/contacts/{cid}/').status_code, 204)
        self.assertFalse(Contact.objects.exists())

    def test_filtros_tipo_e_etiqueta(self):
        self.create(kind='cliente', tags=['vip'])
        self.c.post('/api/v1/contacts/', {'name': 'Perito Paulo', 'kind': 'perito'}, format='json')
        self.assertEqual(self.c.get('/api/v1/contacts/', {'kind': 'perito'}).json()['total'], 1)
        data = self.c.get('/api/v1/contacts/', {'tag': 'vip'}).json()
        self.assertEqual((data['total'], data['tags']), (1, ['vip']))
