from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from aigov.models import GlobalAISwitch
from audit.models import AuditEvent
from backoffice.permissions import user_areas
from billing.models import CreditLot
from cadrius.tests_security import make_org, make_user

REASON = 'Pedido do cliente por e-mail'


def staff(email, *areas, superuser=False):
    user = make_user(email)
    user.is_staff, user.is_superuser = True, superuser
    user.save()
    for area in areas:
        user.groups.add(Group.objects.get_or_create(name={'ti': 'Cadrius TI', 'financeiro': 'Cadrius Financeiro'}[area])[0])
    return user


class Base(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = make_org('Escritório Alfa')
        self.owner = make_user('dono@alfa.com', self.org, role='OWNER')
        self.ti = staff('ti@cadrius.ia.br', 'ti')
        self.fin = staff('fin@cadrius.ia.br', 'financeiro')

    def as_(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


class PermissionTests(Base):
    def test_areas(self):
        self.assertEqual(user_areas(self.ti), ['ti'])
        self.assertEqual(user_areas(staff('root@cadrius.ia.br', superuser=True)), ['financeiro', 'ti'])
        self.assertEqual(user_areas(staff('semgrupo@cadrius.ia.br')), [])   # is_staff sem área não entra
        self.assertEqual(user_areas(self.owner), [])

    def test_customer_and_staff_without_area_are_blocked(self):
        for user in (self.owner, staff('x@cadrius.ia.br')):
            self.assertEqual(self.as_(user).get('/api/v1/backoffice/overview/').status_code, 403)

    def test_area_separation(self):
        self.assertEqual(self.as_(self.fin).get('/api/v1/backoffice/health/').status_code, 403)
        self.assertEqual(self.as_(self.fin).get('/api/v1/backoffice/users/').status_code, 403)
        self.assertEqual(self.as_(self.ti).get('/api/billing/admin/summary/').status_code, 403)
        self.assertEqual(self.as_(self.fin).get('/api/billing/admin/summary/').status_code, 200)

    def test_overview_shows_only_own_area_numbers(self):
        ti = self.as_(self.ti).get('/api/v1/backoffice/overview/').json()
        self.assertIn('ti', ti)
        self.assertNotIn('financeiro', ti)
        fin = self.as_(self.fin).get('/api/v1/backoffice/overview/').json()
        self.assertIn('financeiro', fin)
        self.assertNotIn('ti', fin)
        self.assertEqual(fin['escritorios']['ativos'], 1)

    def test_me(self):
        self.assertEqual(self.as_(self.fin).get('/api/v1/backoffice/me/').json()['areas'], ['financeiro'])


class OrganizationTests(Base):
    def url(self, suffix=''):
        return f'/api/v1/backoffice/organizations/{self.org.pk}/{suffix}'

    def test_list_search_and_detail(self):
        make_org('Outro')
        res = self.as_(self.fin).get('/api/v1/backoffice/organizations/?q=alfa').json()
        self.assertEqual(res['total'], 1)
        self.assertEqual(res['resultados'][0]['membros'], 1)
        detail = self.as_(self.ti).get(self.url()).json()
        self.assertEqual(detail['equipe'][0]['email'], 'dono@alfa.com')
        self.assertIn('creditos', detail)

    def test_filter_by_effective_state(self):
        self.org.subscription_status, self.org.trial_ends_at = 'trialing', timezone.now() - timedelta(days=1)
        self.org.save()
        res = self.as_(self.fin).get('/api/v1/backoffice/organizations/?estado=restricted').json()
        self.assertEqual(res['total'], 1)

    def test_actions_require_reason_and_right_area(self):
        fin = self.as_(self.fin)
        self.assertEqual(fin.post(self.url('actions/'), {'action': 'grant_credits', 'credits': 50}, format='json').status_code, 400)
        self.assertEqual(fin.post(self.url('actions/'), {'action': 'deactivate', 'reason': REASON}, format='json').status_code, 403)
        self.assertEqual(self.as_(self.ti).post(self.url('actions/'), {'action': 'grant_credits', 'credits': 5, 'reason': REASON},
                                                format='json').status_code, 403)

    def test_grant_credits_creates_courtesy_lot_and_audits(self):
        res = self.as_(self.fin).post(self.url('actions/'), {'action': 'grant_credits', 'credits': 50, 'valid_days': 30,
                                                            'reason': REASON}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['avulsos_disponiveis'], 50)
        lot = CreditLot.objects.get(organization=self.org)
        self.assertTrue(lot.stripe_session_id.startswith('manual:'))
        self.assertEqual(lot.amount_paid_cents, 0)
        event = AuditEvent.objects.filter(action='backoffice.action').latest('seq')
        self.assertEqual(event.changes['action'], 'grant_credits')
        self.assertEqual(event.reason, REASON)
        summary = self.as_(self.fin).get('/api/billing/admin/summary/').json()
        self.assertEqual(summary['pacotes_30d']['creditos_vendidos'], 0)       # cortesia não conta como venda
        self.assertEqual(summary['creditos_cortesia_30d'], 50)
        self.assertEqual(self.as_(self.fin).post(self.url('actions/'), {'action': 'grant_credits', 'credits': 999999,
                                                                       'reason': REASON}, format='json').status_code, 400)

    def test_extend_trial_only_for_trials(self):
        fin = self.as_(self.fin)
        body = {'action': 'extend_trial', 'days': 7, 'reason': REASON}
        self.assertEqual(fin.post(self.url('actions/'), body, format='json').status_code, 400)   # escritório ativo
        ends = timezone.now() + timedelta(days=2)
        self.org.subscription_status, self.org.trial_ends_at = 'trialing', ends
        self.org.save()
        self.assertEqual(fin.post(self.url('actions/'), body, format='json').status_code, 200)
        self.org.refresh_from_db()
        self.assertAlmostEqual((self.org.trial_ends_at - ends).days, 7)

    def test_deactivate_org_revokes_member_sessions(self):
        RefreshToken.for_user(self.owner)
        res = self.as_(self.ti).post(self.url('actions/'), {'action': 'deactivate', 'reason': REASON}, format='json')
        self.assertEqual(res.json(), {'ativo': False, 'sessoes_encerradas': 1})
        self.assertTrue(BlacklistedToken.objects.filter(token__user=self.owner).exists())


class UserTests(Base):
    def act(self, user, action, actor=None):
        return self.as_(actor or self.ti).post(f'/api/v1/backoffice/users/{user.pk}/actions/',
                                               {'action': action, 'reason': REASON}, format='json')

    def test_search_by_email_and_encrypted_name(self):
        self.owner.first_name, self.owner.last_name = 'Mariana', 'Souza'
        self.owner.save()
        ti = self.as_(self.ti)
        self.assertEqual(ti.get('/api/v1/backoffice/users/?q=dono@alfa').json()['total'], 1)
        self.assertEqual(ti.get('/api/v1/backoffice/users/?q=marian').json()['resultados'][0]['email'], 'dono@alfa.com')

    def test_deactivate_activate_and_guards(self):
        RefreshToken.for_user(self.owner)
        self.assertEqual(self.act(self.owner, 'deactivate').json()['sessoes_encerradas'], 1)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.assertEqual(self.act(self.owner, 'send_password_reset').status_code, 400)
        self.assertTrue(self.act(self.owner, 'activate').json()['ativo'])
        self.assertEqual(self.act(self.ti, 'deactivate').status_code, 400)                    # a própria conta
        root = staff('root@cadrius.ia.br', superuser=True)
        self.assertEqual(self.act(root, 'deactivate').status_code, 400)                       # superusuário só por superusuário

    def test_unlock_and_password_reset(self):
        with mock.patch('axes.utils.reset') as reset:
            self.assertEqual(self.act(self.owner, 'unlock').status_code, 200)
            reset.assert_called_once_with(username=self.owner.get_username())
        with mock.patch('accounts.password_reset.send_reset_email') as send:
            self.assertTrue(self.act(self.owner, 'send_password_reset').json()['enviado'])
            send.assert_called_once()


class HealthAndSwitchTests(Base):
    def test_health_has_services_queue_config_and_checks_without_secrets(self):
        with self.settings(STRIPE_SECRET_KEY='sk_live_segredo'):
            res = self.as_(self.ti).get('/api/v1/backoffice/health/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['servicos']['banco']['status'], 'ok')
        self.assertTrue(data['config']['stripe'])
        self.assertNotIn('sk_live_segredo', res.content.decode())
        self.assertIn('rotinas', data['fila'])
        self.assertTrue(data['verificacoes'])

    def test_ai_switch_needs_reason_to_turn_off(self):
        ti = self.as_(self.ti)
        self.assertEqual(ti.post('/api/v1/backoffice/ai-switch/', {'enabled': False}, format='json').status_code, 400)
        self.assertFalse(ti.post('/api/v1/backoffice/ai-switch/', {'enabled': False, 'reason': 'Incidente no provedor de IA'},
                                 format='json').json()['ligada'])
        self.assertFalse(GlobalAISwitch.get().ai_enabled)
        self.assertTrue(ti.post('/api/v1/backoffice/ai-switch/', {'enabled': True}, format='json').json()['ligada'])


class LastLoginTests(Base):
    def test_password_login_records_last_access(self):
        self.owner.set_password('Senha-forte-123!')
        self.owner.save()
        res = self.client.post('/api/v1/auth/token/', {'username': self.owner.email, 'password': 'Senha-forte-123!'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.owner.refresh_from_db()
        self.assertIsNotNone(self.owner.last_login)


class CommandTests(Base):
    def test_cadrius_staff_sets_areas(self):
        user = make_user('nova@cadrius.ia.br')
        call_command('cadrius_staff', 'nova@cadrius.ia.br', areas='financeiro', stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertEqual(user_areas(user), ['financeiro'])
        call_command('cadrius_staff', 'nova@cadrius.ia.br', areas='', stdout=StringIO())
        self.assertEqual(user_areas(user), [])
