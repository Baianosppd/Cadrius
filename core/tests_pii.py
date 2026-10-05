"""CAD-152: dados pessoais cifrados em repouso, busca por índice, rotação de chave e anonimização."""
from io import StringIO

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from accounts.models import Organization
from billing.models import SubscriptionPlan
from cadrius.tests_security import make_org, make_user
from core import pii
from core.utils import ENC_PREFIX, decrypt_data
from documents.models import ClientDocument, Document

User = get_user_model()
CPF, CNPJ = '529.982.247-25', '11.222.333/0001-81'


def raw(table, column, pk_column='id', pk=None):
    with connection.cursor() as cur:
        cur.execute(f'SELECT {column} FROM {table}' + (f' WHERE {pk_column} = %s' if pk is not None else ''),
                    [str(pk).replace('-', '')] if pk is not None and connection.vendor == 'sqlite' else ([pk] if pk is not None else []))
        return cur.fetchone()[0]


class PiiIndexTests(TestCase):
    def test_busca_parcial_sem_acento_e_tokens_nao_revelam_o_nome(self):
        stored = pii.search_tokens('t', 'Maria da Silva')
        self.assertNotIn('maria', stored.lower())
        for term in ('silv', 'MARIA', 'ria da', 'ma', 'm', 'ilva', 'da s'):
            self.assertTrue(all(f' {t} ' in stored for t in pii.query_tokens('t', term)), term)
        for term in ('joao', 'xyz', 'silvio'):
            self.assertFalse(all(f' {t} ' in stored for t in pii.query_tokens('t', term)), term)
        self.assertTrue(all(f' {t} ' in pii.search_tokens('t', 'João Álvares') for t in pii.query_tokens('t', 'joao alvar')))

    def test_indice_cego_normaliza_e_depende_da_finalidade(self):
        self.assertEqual(pii.blind_index('a', CPF), pii.blind_index('a', '52998224725'))
        self.assertNotEqual(pii.blind_index('a', CPF), pii.blind_index('b', CPF))
        self.assertIsNone(pii.blind_index('a', ''))
        self.assertIsNone(pii.blind_index('a', None))


class AtRestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana@example.com', 'ana@example.com', 'Str0ng-Passw0rd!x', first_name='Ana',
                                             last_name='Souza Lima', cpf=CPF, phone='(11) 91234-5678', oab_number='123456')
        self.plan = SubscriptionPlan.objects.create(name='F', tier='FREE', price_brl=0, max_users=5, max_ai_extractions=10)
        self.org = Organization.objects.create(name='Silva Advocacia', plan=self.plan, cnpj=CNPJ, main_phone='1133334444',
                                               street='Rua das Flores', number='100', cep='01000-000', corporate_email='c@silva.adv.br')

    def test_o_banco_so_tem_texto_cifrado(self):
        table = User._meta.db_table
        # Confere o valor completo: fragmentos curtos ("529", "Ana") podem aparecer por acaso no base64 do cifrado (teste instável)
        for col, plain in (('cpf', CPF), ('phone', '(11) 91234-5678'), ('oab_number', '123456'), ('first_name', 'Ana'),
                           ('last_name', 'Souza Lima')):
            value = raw(table, col, pk=self.user.pk)
            self.assertTrue(value.startswith(ENC_PREFIX), col)
            self.assertEqual(decrypt_data(value), plain, col)
            if len(plain) >= 6:
                self.assertNotIn(plain, value, col)
        otable = Organization._meta.db_table
        for col in ('cnpj', 'main_phone', 'street', 'number', 'cep', 'corporate_email'):
            self.assertTrue(raw(otable, col, pk=self.org.pk).startswith(ENC_PREFIX), col)
        self.assertEqual(raw(table, 'email', pk=self.user.pk), 'ana@example.com')  # login continua em claro (decisão)

    def test_python_enxerga_o_valor_em_claro(self):
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual((user.cpf, user.first_name, user.phone, user.oab_number), (CPF, 'Ana', '(11) 91234-5678', '123456'))
        self.assertEqual(Organization.objects.get(pk=self.org.pk).cnpj, CNPJ)

    def test_cpf_e_cnpj_unicos_pelo_indice_cego_em_qualquer_formato(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user('b@example.com', 'b@example.com', 'x', cpf='52998224725')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Organization.objects.create(name='Outra', plan=self.plan, cnpj='11222333000181')
        self.assertTrue(User.objects.filter(cpf_bidx=pii.blind_index('user.cpf', '529.982.247-25')).exists())

    def test_save_com_update_fields_mantem_o_indice_em_dia(self):
        self.user.first_name = 'Beatriz'
        self.user.save(update_fields=['first_name'])
        stored = User.objects.values_list('name_idx', flat=True).get(pk=self.user.pk)
        self.assertTrue(all(f' {t} ' in stored for t in pii.query_tokens('user.name', 'beatri')))
        self.assertFalse(all(f' {t} ' in stored for t in pii.query_tokens('user.name', 'ana')))

    def test_anonimizacao_limpa_dados_e_indices(self):
        from privacy.dsr import anonymize_user
        anonymize_user(self.user)
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual((user.cpf, user.cpf_bidx, user.first_name, user.name_idx), (None, None, '', ''))
        # o CPF fica livre para um novo cadastro
        User.objects.create_user('novo@example.com', 'novo@example.com', 'x', cpf=CPF)


class EncryptPiiCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana@example.com', 'ana@example.com', 'x', first_name='Ana', cpf=CPF)

    def legacy_plaintext(self):
        with connection.cursor() as cur:
            cur.execute(f"UPDATE {User._meta.db_table} SET cpf = %s, first_name = %s, cpf_bidx = NULL, name_idx = '' WHERE email = %s",
                        [CPF, 'Ana', 'ana@example.com'])

    def test_dry_run_conta_e_comando_cifra_e_reindexa(self):
        self.legacy_plaintext()
        out = StringIO()
        call_command('encrypt_pii', '--dry-run', stdout=out)
        self.assertIn('antes: 2', out.getvalue())  # cpf + first_name
        self.assertTrue(pii.plaintext_counts()[f'{User._meta.db_table}.cpf'] == 1)
        call_command('encrypt_pii', stdout=StringIO())
        self.assertEqual(sum(pii.plaintext_counts().values()), 0)
        user = User.objects.get(email='ana@example.com')
        self.assertEqual((user.cpf, user.first_name), (CPF, 'Ana'))
        self.assertEqual(user.cpf_bidx, pii.blind_index('user.cpf', CPF))   # índice recalculado

    def test_check_de_conformidade_detecta_texto_puro(self):
        from compliance import checks
        self.assertEqual(checks._pii_encrypted().status, checks.PASS)
        self.legacy_plaintext()
        self.assertEqual(checks._pii_encrypted().status, checks.FAIL)

    def test_rotacao_de_chave(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        self.user.delete()   # criado com a chave derivada de teste, que não faz parte deste cenário de rotação
        with override_settings(ENCRYPTION_KEY=old):
            User.objects.create_user('b@example.com', 'b@example.com', 'x', first_name='Bia', cpf='111.444.777-35')
            before = raw(User._meta.db_table, 'first_name', pk=User.objects.get(email='b@example.com').pk)
        with override_settings(ENCRYPTION_KEY=f'{new},{old}'):           # nova primeiro, antiga ainda decifra
            call_command('encrypt_pii', stdout=StringIO())
            after = raw(User._meta.db_table, 'first_name', pk=User.objects.get(email='b@example.com').pk)
        self.assertNotEqual(before, after)
        with override_settings(ENCRYPTION_KEY=new):                      # a antiga já pode ser removida
            self.assertEqual(decrypt_data(after), 'Bia')
            self.assertEqual(User.objects.get(email='b@example.com').cpf, '111.444.777-35')


class SearchApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('o@example.com', self.org, role='OWNER')
        for email, first, last in (('m1@example.com', 'Márcia', 'Silva'), ('m2@example.com', 'Carlos', 'Souza'),
                                   ('m3@example.com', 'Ana', 'Beatriz Silveira')):
            u = make_user(email, self.org)
            u.first_name, u.last_name = first, last
            u.save()
        from privacy import consent
        for u in User.objects.all():
            for doc in consent.current_documents(consent.REQUIRED_KINDS):
                consent.record_consent(u, doc)
        self.client.force_authenticate(self.owner)

    def names(self, q=''):
        resp = self.client.get('/api/v1/funcionarios/', {'q': q} if q else {})
        self.assertEqual(resp.status_code, 200, resp.data)
        return [row['name'].split()[0] for row in resp.data]

    def test_lista_ordenada_por_nome_apesar_de_cifrado(self):
        firsts = [n.casefold() for n in self.names() if '@' not in n]   # quem não tem nome aparece pelo e-mail
        self.assertEqual(firsts, sorted(firsts))
        self.assertGreaterEqual(len(firsts), 3)

    def test_busca_parcial_por_nome_sem_acento_e_por_email(self):
        self.assertEqual(sorted(self.names('silv')), ['Ana', 'Márcia'])      # Silva e Silveira
        self.assertEqual(self.names('marcia'), ['Márcia'])                     # sem acento
        self.assertEqual(self.names('souza'), ['Carlos'])
        self.assertEqual(self.names('m2@example'), ['Carlos'])                 # por e-mail
        self.assertEqual(self.names('zzzz'), [])

    def test_documentos_busca_por_cliente_cifrado(self):
        doc = Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Contrato', tipo='contrato',
                                      status='pendente', arquivo='documents/x.pdf')
        other = Document.objects.create(organization=self.org, uploaded_by=self.owner, nome='Petição', tipo='peticao',
                                        status='pendente', arquivo='documents/y.pdf')
        ClientDocument.objects.create(nome_cliente='Construtora João da Silva Ltda', documento=doc)
        ClientDocument.objects.create(nome_cliente='Maria Oliveira', documento=other)
        self.assertEqual(raw(ClientDocument._meta.db_table, 'nome_cliente', pk=ClientDocument.objects.first().pk)[:5], ENC_PREFIX)
        resp = self.client.get('/api/v1/documentos/', {'cliente': 'joao silv'})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual([r['nome'] for r in resp.data['results']], ['Contrato'])
        self.assertEqual(resp.data['results'][0]['cliente'], 'Construtora João da Silva Ltda')  # subquery decifra
        self.assertEqual(self.client.get('/api/v1/documentos/', {'cliente': 'xyz'}).data['results'], [])
