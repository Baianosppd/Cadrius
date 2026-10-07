from django.urls import reverse
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from cadrius.tests_security import legal_acceptance

User = get_user_model()

class AccountTests(APITestCase):
    """
    Suite de testes para os endpoints do app 'accounts'.
    """

    def setUp(self):
        """
        Configuração inicial para os testes.
        Cria um usuário de teste.
        """
        self.test_user_data = {
            'email': 'testuser@example.com',
            'first_name': 'Test',
            'last_name': 'User',
            'password': 'strong-password-123'
        }
        self.user = User.objects.create_user(
            username=self.test_user_data['email'],
            email=self.test_user_data['email'],
            password=self.test_user_data['password'],
            first_name=self.test_user_data['first_name'],
            last_name=self.test_user_data['last_name']
        )

    def test_get_user_profile_authenticated(self):
        """
        Testa se um usuário autenticado pode obter seu perfil.
        """
        url = reverse('user_profile')
        self.client.force_authenticate(user=self.user) # Força a autenticação
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.test_user_data['email'])
        self.assertEqual(response.data['first_name'], self.test_user_data['first_name'])

    def test_get_user_profile_unauthenticated(self):
        """
        Testa se um usuário não autenticado é bloqueado de ver o perfil.
        """
        url = reverse('user_profile')
        response = self.client.get(url)

        # O esperado é 401 Unauthorized ou 403 Forbidden, dependendo da config
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_patch_user_profile_authenticated(self):
        url = reverse('user_profile_update')
        self.client.force_authenticate(user=self.user)
        data = {
            'first_name': 'João',
            'last_name': 'Silva',
            'phone': '(11) 99999-9999',
            'oab_number': 'SP 123456',
        }
        response = self.client.patch(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['first_name'], 'João')
        self.assertEqual(response.data['last_name'], 'Silva')
        self.assertEqual(response.data['phone'], '(11) 99999-9999')
        self.assertEqual(response.data['oab_number'], 'SP 123456')

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'João')
        self.assertEqual(self.user.oab_number, 'SP 123456')

    def test_patch_user_profile_partial(self):
        url = reverse('user_profile_update')
        self.client.force_authenticate(user=self.user)
        response = self.client.patch(url, {'phone': '(21) 98888-7777'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['phone'], '(21) 98888-7777')
        self.assertEqual(response.data['first_name'], self.test_user_data['first_name'])

    def test_patch_user_profile_unauthenticated(self):
        url = reverse('user_profile_update')
        response = self.client.patch(url, {'first_name': 'João'}, format='json')

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_change_password_success(self):
        url = reverse('change_password')
        self.client.force_authenticate(user=self.user)
        data = {
            'current_password': self.test_user_data['password'],
            'new_password': 'new-strong-password-456',
            'confirm_password': 'new-strong-password-456',
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], 'Senha alterada com sucesso.')

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-strong-password-456'))
        self.assertFalse(self.user.check_password(self.test_user_data['password']))

    def test_change_password_wrong_current(self):
        url = reverse('change_password')
        self.client.force_authenticate(user=self.user)
        data = {
            'current_password': 'wrong-password',
            'new_password': 'new-strong-password-456',
            'confirm_password': 'new-strong-password-456',
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('current_password', response.data)

    def test_change_password_mismatch(self):
        url = reverse('change_password')
        self.client.force_authenticate(user=self.user)
        data = {
            'current_password': self.test_user_data['password'],
            'new_password': 'new-strong-password-456',
            'confirm_password': 'different-password',
        }
        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('confirm_password', response.data)

    def test_change_password_unauthenticated(self):
        url = reverse('change_password')
        response = self.client.post(
            url,
            {
                'current_password': 'x',
                'new_password': 'y',
                'confirm_password': 'y',
            },
            format='json',
        )

        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class TeamMemberTests(APITestCase):
    def setUp(self):
        from billing.models import SubscriptionPlan
        from accounts.models import Organization, OrganizationMembership

        self.plan = SubscriptionPlan.objects.create(
            name='Pro',
            tier='PRO',
            price_brl=99,
            max_users=5,
            max_ai_extractions=1000,
        )
        self.org = Organization.objects.create(name='Escritório Teste', plan=self.plan)
        self.owner = User.objects.create_user(
            username='owner@example.com',
            email='owner@example.com',
            password='strong-password-123',
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role='OWNER',
        )
        self.member = User.objects.create_user(
            username='member@example.com',
            email='member@example.com',
            password='strong-password-123',
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=self.org,
            role='MEMBER',
        )

    def test_list_team_members(self):
        url = reverse('team-members')
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['role'], 'owner')

    def test_invite_team_member(self):
        url = reverse('team-members')
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            url,
            {'email': 'funcionario@empresa.com', 'role': 'advogado_pleno'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['email'], 'funcionario@empresa.com')
        self.assertEqual(response.data['role'], 'advogado_pleno')
        self.assertTrue(User.objects.filter(email='funcionario@empresa.com').exists())

    def test_invite_forbidden_for_member_role(self):
        url = reverse('team-members')
        self.client.force_authenticate(user=self.member)
        response = self.client.post(
            url,
            {'email': 'novo@empresa.com', 'role': 'advogado_pleno'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class FuncionariosListTests(APITestCase):
    def setUp(self):
        from billing.models import SubscriptionPlan
        from accounts.models import Organization, OrganizationMembership

        self.plan = SubscriptionPlan.objects.create(
            name='Pro Func',
            tier='PRO',
            price_brl=99,
            max_users=5,
            max_ai_extractions=1000,
        )
        self.org = Organization.objects.create(name='Escritório Func', plan=self.plan)
        self.owner = User.objects.create_user(
            username='func-owner@example.com',
            email='func-owner@example.com',
            password='strong-password-123',
            first_name='João',
            last_name='Silva',
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role='OWNER',
        )
        self.member = User.objects.create_user(
            username='func-member@example.com',
            email='func-member@example.com',
            password='strong-password-123',
            first_name='Maria',
            last_name='Souza',
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=self.org,
            role='MEMBER',
        )
        # Outro escritório — não deve aparecer
        other_org = Organization.objects.create(name='Outro Escritório', plan=self.plan)
        outsider = User.objects.create_user(
            username='outsider@example.com',
            email='outsider@example.com',
            password='strong-password-123',
        )
        OrganizationMembership.objects.create(
            user=outsider,
            organization=other_org,
            role='OWNER',
        )

    def test_list_funcionarios_of_logged_organization(self):
        url = reverse('funcionarios-list')
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        user_ids = {item['user_id'] for item in response.data}
        self.assertIn(str(self.owner.id), {str(uid) for uid in user_ids})
        self.assertIn(str(self.member.id), {str(uid) for uid in user_ids})
        names = {item['name'] for item in response.data}
        self.assertIn('João Silva', names)
        self.assertIn('Maria Souza', names)

    def test_list_funcionarios_unauthenticated(self):
        response = self.client.get(reverse('funcionarios-list'))
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class PermissionGroupTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='groups@example.com',
            email='groups@example.com',
            password='strong-password-123',
        )

    def test_list_permission_groups_authenticated(self):
        url = reverse('team-permission-groups')
        self.client.force_authenticate(user=self.user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        self.assertEqual(response.data[0]['name'], 'Admin')
        self.assertIn('Ver documentos', response.data[0]['permissions'])
        self.assertEqual(response.data[2]['name'], 'Estagiário')

    def test_list_permission_groups_unauthenticated(self):
        response = self.client.get(reverse('team-permission-groups'))
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


class RegistrationTests(APITestCase):
    VALID_CPF = '529.982.247-25'
    OTHER_CPF = '111.444.777-35'
    VALID_CNPJ = '11.222.333/0001-81'

    def setUp(self):
        cache.clear()  # o limite de cadastro (5/h) acumula no Redis entre os testes
        from billing.models import SubscriptionPlan

        self.plan = SubscriptionPlan.objects.create(
            name='Starter',
            tier='FREE',
            price_brl=0,
            max_users=1,
            max_ai_extractions=5,
        )

    def _individual_payload(self, **overrides):
        data = {
            'nome_completo': 'Maria Silva Santos',
            'cpf': self.VALID_CPF,
            'email': 'maria@email.com',
            'senha': 'Cadrius#2026',
            'plano_id': self.plan.id,
            **legal_acceptance(),
        }
        data.update(overrides)
        return data

    def _company_payload(self, **overrides):
        data = {
            'razao_social': 'Silva & Associados Ltda',
            'nome_fantasia': 'Silva Advocacia',
            'cnpj': self.VALID_CNPJ,
            'porte_empresa': 'EPP',
            'gerente': {
                'nome_completo': 'João Silva Santos',
                'cpf': self.OTHER_CPF,
                'email': 'joao@empresa.com',
                'senha': 'Cadrius#2026',
                'cargo': 'Gerente Jurídico',
            },
            'plano_id': self.plan.id,
            **legal_acceptance(),
        }
        data.update(overrides)
        return data

    def test_individual_registration_creates_user_org_and_tokens(self):
        from accounts.models import OrganizationMembership

        response = self.client.post(
            reverse('user_register'),
            self._individual_payload(oab_numero='123456', oab_uf='GO', area_atuacao='previdenciario'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertEqual(response.data['organization']['account_type'], 'PESSOA_FISICA')

        user = User.objects.get(email='maria@email.com')
        self.assertEqual((user.first_name, user.last_name), ('Maria', 'Silva Santos'))
        self.assertEqual(user.cpf, self.VALID_CPF)
        self.assertEqual((user.oab_number, user.oab_uf, user.practice_area), ('123456', 'GO', 'previdenciario'))
        membership = OrganizationMembership.objects.get(user=user)
        self.assertEqual(membership.role, 'OWNER')
        self.assertEqual(membership.organization.plan, self.plan)

    def test_individual_oab_is_optional(self):
        response = self.client.post(reverse('user_register'), self._individual_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(User.objects.get(email='maria@email.com').oab_number)

    def test_individual_required_fields(self):
        response = self.client.post(reverse('user_register'), {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        for field in ('nome_completo', 'cpf', 'email', 'senha', 'plano_id'):
            self.assertIn(field, response.data)

    def test_rejects_invalid_cpf_short_password_and_duplicate_email(self):
        User.objects.create_user(username='maria@email.com', email='maria@email.com', password='x')

        response = self.client.post(
            reverse('user_register'),
            self._individual_payload(cpf='123.456.789-00', senha='curta'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cpf', response.data)
        self.assertIn('email', response.data)

    def test_rejects_short_password(self):
        response = self.client.post(
            reverse('user_register'),
            self._individual_payload(senha='abc12'),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('senha', response.data)

    def test_rejects_inactive_plan(self):
        self.plan.is_active = False
        self.plan.save()

        response = self.client.post(reverse('user_register'), self._individual_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('plano_id', response.data)

    def test_company_registration_creates_org_and_manager(self):
        from accounts.models import Organization, OrganizationMembership

        response = self.client.post(
            reverse('company_register'),
            self._company_payload(
                tipo_sociedade='LTDA',
                regime_tributario='SIMPLES_NACIONAL',
                cep='01310100',
                logradouro='Av. Paulista',
                numero='1000',
                bairro='Bela Vista',
                cidade='São Paulo',
                uf='SP',
                telefone_principal='(11) 98765-4321',
                email_corporativo='contato@empresa.com',
            ),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIn('access', response.data)
        from core.pii import blind_index
        org = Organization.objects.get(cnpj_bidx=blind_index("org.cnpj", self.VALID_CNPJ))
        self.assertEqual(org.account_type, 'EMPRESA')
        self.assertEqual(org.razao_social, 'Silva & Associados Ltda')
        self.assertEqual(org.name, 'Silva Advocacia')
        self.assertEqual(org.company_type, 'LTDA')
        self.assertEqual(org.company_size, 'EPP')
        self.assertEqual(org.tax_regime, 'SIMPLES_NACIONAL')
        self.assertEqual(org.cep, '01310-100')
        self.assertEqual(org.corporate_email, 'contato@empresa.com')

        membership = OrganizationMembership.objects.get(organization=org)
        self.assertEqual(membership.user.email, 'joao@empresa.com')
        self.assertEqual(membership.role, 'OWNER')
        self.assertEqual(membership.job_title, 'Gerente Jurídico')

    def test_company_optional_fields_can_be_omitted(self):
        response = self.client.post(reverse('company_register'), self._company_payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_company_required_fields(self):
        response = self.client.post(reverse('company_register'), {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        for field in ('razao_social', 'nome_fantasia', 'cnpj', 'porte_empresa', 'gerente', 'plano_id'):
            self.assertIn(field, response.data)

    def test_company_rejects_invalid_and_duplicate_cnpj(self):
        invalid = self.client.post(
            reverse('company_register'),
            self._company_payload(cnpj='11.222.333/0001-00'),
            format='json',
        )
        self.assertIn('cnpj', invalid.data)

        self.client.post(reverse('company_register'), self._company_payload(), format='json')
        duplicate = self.client.post(
            reverse('company_register'),
            self._company_payload(gerente={
                'nome_completo': 'Outra Pessoa',
                'cpf': '390.533.447-05',
                'email': 'outra@empresa.com',
                'senha': 'Cadrius#2026',
            }),
            format='json',
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cnpj', duplicate.data)

    def test_company_manager_errors_are_nested(self):
        response = self.client.post(
            reverse('company_register'),
            self._company_payload(gerente={'nome_completo': 'João', 'cpf': '000', 'email': 'x', 'senha': '1'}),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cpf', response.data['gerente'])
        self.assertIn('email', response.data['gerente'])

    def test_registered_user_can_login(self):
        self.client.post(reverse('user_register'), self._individual_payload(), format='json')

        response = self.client.post(
            reverse('token_obtain_pair'),
            {'username': 'maria@email.com', 'password': 'Cadrius#2026'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


class TeamCreditsTests(APITestCase):
    def setUp(self):
        from billing.models import SubscriptionPlan
        from accounts.models import Organization, OrganizationMembership

        self.plan = SubscriptionPlan.objects.create(
            name='Pro Créditos',
            tier='PRO',
            price_brl=99,
            max_users=5,
            max_ai_extractions=100,
        )
        self.org = Organization.objects.create(name='Escritório Créditos', plan=self.plan)
        self.owner = User.objects.create_user(
            username='credit-owner@example.com',
            email='credit-owner@example.com',
            password='strong-password-123',
        )
        self.owner_membership = OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role='OWNER',
        )
        self.member = User.objects.create_user(
            username='credit-member@example.com',
            email='credit-member@example.com',
            password='strong-password-123',
        )
        self.member_membership = OrganizationMembership.objects.create(
            user=self.member,
            organization=self.org,
            role='MEMBER',
        )

    def _set_limit(self, user, membership, value):
        self.client.force_authenticate(user=user)
        return self.client.patch(
            reverse('team-member-credits', args=[membership.pk]),
            {'creditos_limite': value},
            format='json',
        )

    def test_members_list_includes_credits_and_status(self):
        from billing.credits import consume_credit

        consume_credit(self.org, user_id=self.member.id)
        consume_credit(self.org, user_id=self.member.id)

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse('team-members'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        member_row = next(r for r in response.data if r['email'] == 'credit-member@example.com')
        self.assertEqual(member_row['creditos_usados'], 2)
        self.assertIsNone(member_row['creditos_limite'])
        self.assertEqual(member_row['status'], 'ativo')

    def test_owner_sets_member_limit(self):
        response = self._set_limit(self.owner, self.member_membership, 30)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['creditos_limite'], 30)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.credit_limit, 30)

    def test_member_cannot_set_limit(self):
        response = self._set_limit(self.member, self.member_membership, 30)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_limits_cannot_exceed_plan_total(self):
        self._set_limit(self.owner, self.owner_membership, 80)
        response = self._set_limit(self.owner, self.member_membership, 30)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('creditos_limite', response.data)

    def test_member_blocked_when_individual_limit_reached(self):
        from billing.credits import MEMBER_LIMIT_MESSAGE, consume_credit, organization_credits_used

        self._set_limit(self.owner, self.member_membership, 2)

        self.assertTrue(consume_credit(self.org, user_id=self.member.id)[0])
        self.assertTrue(consume_credit(self.org, user_id=self.member.id)[0])
        ok, message = consume_credit(self.org, user_id=self.member.id)

        self.assertFalse(ok)
        self.assertEqual(message, MEMBER_LIMIT_MESSAGE)
        self.assertEqual(organization_credits_used(self.org), 2)
        # outro membro sem cota continua a consumir do plano
        self.assertTrue(consume_credit(self.org, user_id=self.owner.id)[0])

    def test_plan_limit_blocks_everyone(self):
        from billing.credits import PLAN_LIMIT_MESSAGE, consume_credit

        self.plan.max_ai_extractions = 1
        self.plan.save()

        self.assertTrue(consume_credit(self.org, user_id=self.owner.id)[0])
        ok, message = consume_credit(self.org, user_id=self.member.id)

        self.assertFalse(ok)
        self.assertEqual(message, PLAN_LIMIT_MESSAGE)

    def test_credits_summary(self):
        from billing.credits import consume_credit

        self._set_limit(self.owner, self.member_membership, 40)
        consume_credit(self.org, user_id=self.member.id)

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse('team-credits'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {
            'creditos_total': 100,
            'creditos_usados': 1,
            'creditos_disponiveis': 99,
            'creditos_distribuidos': 40,
            'creditos_nao_distribuidos': 60,
            'creditos_avulsos': 0,
            'uso_por_atividade': [],                 # CAD-225: pedidos à IA no mês (aqui nenhum)
        })

class UserProfileContextTests(APITestCase):
    """GET /auth/user/ expõe escritório, papel e is_staff (o front decide as telas por eles)."""

    def test_profile_inclui_organizacao_e_papel(self):
        from cadrius.tests_security import make_org, make_user
        org = make_org('Escritório Perfil')
        user = make_user('perfil@example.com', org=org)
        self.client.force_authenticate(user)
        resp = self.client.get('/api/v1/auth/user/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['organization']['name'], 'Escritório Perfil')
        self.assertIn(resp.data['role'], {'OWNER', 'ADMIN', 'MEMBER', 'VIEWER'})
        self.assertFalse(resp.data['is_staff'])

    def test_profile_sem_escritorio(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user('solo@example.com', 'solo@example.com', 'Str0ng-Passw0rd!x')
        self.client.force_authenticate(user)
        resp = self.client.get('/api/v1/auth/user/')
        self.assertIsNone(resp.data['organization'])
        self.assertIsNone(resp.data['role'])
