"""CAD-223: grupos de acesso definidos pelo dono/admin e níveis de acesso da equipe Cadrius."""
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts import access
from accounts.models import AccessGroup, OrganizationMembership
from audit.models import AuditEvent
from cadrius.tests_security import make_org, make_user

BASE = '/api/v1/teams/'


class AccessGroupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org()
        self.owner = make_user('dono@x.com', self.org, role='OWNER')
        self.member = make_user('estag@x.com', self.org, role='MEMBER')
        self.viewer = make_user('leitor@x.com', self.org, role='VIEWER')
        self.m = OrganizationMembership.objects.get(user=self.member)

    def as_(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def jwt(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken
        from privacy import consent
        for doc in consent.current_documents(consent.REQUIRED_KINDS):
            consent.record_consent(user, doc)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return c

    def test_catalogo_aberto_a_equipe_e_grupos_so_para_gestor(self):
        cat = self.as_(self.member).get(f'{BASE}access/catalog/').json()
        self.assertIn('financeiro', [m['chave'] for m in cat['modulos']])
        self.assertTrue(all(m['ver'] and m['editar'] for m in cat['modulos']))
        self.assertIsNone(cat['meu_acesso'])
        self.assertEqual(self.as_(self.member).get(f'{BASE}access/groups/').status_code, 403)
        self.assertEqual(self.as_(self.owner).get(f'{BASE}access/groups/').status_code, 200)

    def test_criar_por_modelo_e_editar_normaliza(self):
        owner = self.as_(self.owner)
        res = owner.post(f'{BASE}access/groups/', {'modelo': 'financeiro'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn('financeiro.ver', res.data['permissoes'])
        bad = owner.post(f'{BASE}access/groups/', {'nome': 'X', 'permissoes': ['root.tudo']}, format='json')
        self.assertEqual(bad.status_code, 400)
        g = owner.post(f'{BASE}access/groups/', {'nome': 'Estagiários', 'permissoes': ['contatos.editar', 'marketing.aprovar']},
                       format='json').data
        self.assertEqual(set(g['permissoes']), {'contatos.ver', 'contatos.editar', 'marketing.ver', 'marketing.editar', 'marketing.aprovar'})
        dup = owner.post(f'{BASE}access/groups/', {'nome': 'Estagiários', 'permissoes': []}, format='json')
        self.assertEqual(dup.status_code, 400)

    def test_grupo_restringe_modulos_pela_api(self):
        g = AccessGroup.objects.create(organization=self.org, name='Estagiários', permissions=access.clean(['contatos.ver', 'tarefas.editar']))
        res = self.as_(self.owner).patch(f'{BASE}members/{self.m.pk}/access/', {'grupo_id': g.pk}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['grupo']['nome'], 'Estagiários')
        c = self.jwt(self.member)
        self.assertEqual(c.get('/api/v1/contacts/').status_code, 200)
        blocked = c.post('/api/v1/contacts/', {'name': 'Novo'}, format='json')
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()['detail'], access.ModuleForbidden.default_detail)
        self.assertEqual(c.get('/api/v1/carteira/painel/').status_code, 403)
        self.assertEqual(c.get('/api/v1/minutas/').status_code, 403)
        profile = c.get('/api/v1/auth/user/').json()
        self.assertEqual(profile['acessos']['grupo'], 'Estagiários')
        self.assertTrue(AuditEvent.objects.filter(action='team.access_assigned').exists())

    def test_grupo_libera_financeiro_a_membro(self):
        c = self.jwt(self.member)
        self.assertEqual(c.get('/api/v1/carteira/painel/').status_code, 403)          # sem grupo: cargo (só dono/admin)
        g = AccessGroup.objects.create(organization=self.org, name='Financeiro', permissions=access.clean(['financeiro.editar']))
        self.m.access_group = g
        self.m.save()
        self.assertEqual(c.get('/api/v1/carteira/painel/').status_code, 200)
        self.assertEqual(c.get('/api/v1/carteira/lancamentos/').status_code, 200)

    def test_leitura_nunca_altera_e_gestor_nao_entra_em_grupo(self):
        g = AccessGroup.objects.create(organization=self.org, name='Tudo', permissions=access.clean(['contatos.editar']))
        vm = OrganizationMembership.objects.get(user=self.viewer)
        vm.access_group = g
        vm.save()
        self.assertEqual(access.effective(vm), {'contatos.ver'})
        om = OrganizationMembership.objects.get(user=self.owner)
        res = self.as_(self.owner).patch(f'{BASE}members/{om.pk}/access/', {'grupo_id': g.pk}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_apagar_grupo_volta_ao_cargo(self):
        g = AccessGroup.objects.create(organization=self.org, name='Temp', permissions=['contatos.ver'])
        self.m.access_group = g
        self.m.save()
        self.assertEqual(self.as_(self.owner).delete(f'{BASE}access/groups/{g.pk}/').status_code, 204)
        self.m.refresh_from_db()
        self.assertIsNone(self.m.access_group)
        self.assertIsNone(access.effective(self.m))

    def test_assistente_respeita_o_grupo(self):
        from assistant.engine import Ctx
        from assistant.tools import TOOLS, tool_permitted
        ctx = Ctx(org=self.org, user=self.member, role='MEMBER', perms=access.clean(['contatos.ver', 'ia.ver']))
        self.assertTrue(tool_permitted(ctx, TOOLS['buscar_contatos']))
        self.assertFalse(tool_permitted(ctx, TOOLS['criar_contato']))           # ação pede "editar"
        self.assertFalse(tool_permitted(ctx, TOOLS['resumo_financeiro']))
        self.assertFalse(tool_permitted(ctx, TOOLS['criar_regra']))
        ctx.perms = set(access.clean(['automacoes.gerir', 'financeiro.ver']))
        self.assertTrue(tool_permitted(ctx, TOOLS['criar_regra']))
        self.assertTrue(tool_permitted(ctx, TOOLS['resumo_financeiro']))
        legacy = Ctx(org=self.org, user=self.member, role='MEMBER')
        self.assertFalse(tool_permitted(legacy, TOOLS['criar_regra']))           # sem grupo: como antes


class StaffLevelTests(TestCase):
    def setUp(self):
        cache.clear()
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.ti = U.objects.create_user(username='ti@cadrius.com', email='ti@cadrius.com', password='x-Str0ng-Pass!', is_staff=True,
                                        is_superuser=True)
        self.fin = U.objects.create_user(username='fin@cadrius.com', email='fin@cadrius.com', password='x-Str0ng-Pass!', is_staff=True)

    def test_area_so_consulta_le_mas_nao_altera(self):
        from backoffice import staff
        from backoffice.permissions import HasArea, user_area_levels
        row = staff.update_staff(self.ti, self.fin, areas=['suporte'], read_only=['fiscal', 'suporte'], reason='Ajuste de áreas da equipe')
        self.assertEqual(row['niveis'], {'suporte': 'total', 'fiscal': 'consulta'})
        self.assertTrue(Group.objects.filter(name='Cadrius Fiscal (consulta)', user=self.fin).exists())
        self.assertEqual(user_area_levels(self.fin)['fiscal'], 'consulta')
        from django.test import RequestFactory
        from unittest import mock
        perm = HasArea.of('fiscal')()
        rf = RequestFactory()
        with mock.patch('accounts.mfa.staff_session_ok', return_value=True):
            get = rf.get('/')
            get.user = self.fin
            post = rf.post('/')
            post.user = self.fin
            self.assertTrue(perm.has_permission(get, None))
            self.assertFalse(perm.has_permission(post, None))
        self.assertTrue(AuditEvent.objects.filter(action='staff.areas_changed').exists())
