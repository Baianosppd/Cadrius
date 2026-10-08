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
        user.groups.add(Group.objects.get_or_create(name={'ti': 'Cadrius TI', 'financeiro': 'Cadrius Financeiro', 'fiscal': 'Cadrius Fiscal', 'suporte': 'Cadrius Suporte', 'marketing': 'Cadrius Marketing'}[area])[0])
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
        client.force_authenticate(user, token={'amr': 'mfa'})   # sessão com MFA (CAD-169)
        return client


class PermissionTests(Base):
    def test_areas(self):
        self.assertEqual(user_areas(self.ti), ['ti'])
        self.assertEqual(user_areas(staff('root@cadrius.ia.br', superuser=True)), ['financeiro', 'fiscal', 'juridico', 'marketing', 'suporte', 'ti'])
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


class SeedValidationUsersTests(Base):
    def test_cria_contas_e_escritorios_de_teste_sem_repetir_e_remove(self):
        out = StringIO()
        call_command('seed_validation_users', stdout=out)
        from django.contrib.auth import get_user_model
        from accounts.models import Organization
        from billing import entitlements as ent
        users = get_user_model().objects.filter(email__endswith='@teste.cadrius.ia.br')
        self.assertEqual(users.count(), 17)
        self.assertEqual(user_areas(users.get(email='gestao.completa@teste.cadrius.ia.br')), ['financeiro', 'fiscal', 'juridico', 'marketing', 'suporte', 'ti'])
        self.assertEqual(user_areas(users.get(email='gestao.marketing@teste.cadrius.ia.br')), ['marketing'])
        self.assertEqual(user_areas(users.get(email='gestao.fiscal@teste.cadrius.ia.br')), ['fiscal'])
        self.assertEqual(user_areas(users.get(email='gestao.semarea@teste.cadrius.ia.br')), [])
        states = {o.name: ent.effective_status(o) for o in Organization.objects.filter(name__startswith='[TESTE]')}
        self.assertEqual(states, {'[TESTE] Ativo': 'active', '[TESTE] Em teste': 'trialing', '[TESTE] Teste vencido': 'restricted',
                                  '[TESTE] Pagamento pendente': 'past_due', '[TESTE] Restrito': 'restricted',
                                  '[TESTE] Suspenso': 'suspended', '[TESTE] Cancelado': 'canceled'})
        # senhas aparecem uma vez e funcionam
        line = next(li for li in out.getvalue().splitlines() if li.startswith('dono@teste'))
        password = line.split()[1]
        self.assertTrue(users.get(email='dono@teste.cadrius.ia.br').check_password(password))
        out2 = StringIO()
        call_command('seed_validation_users', stdout=out2)                       # idempotente
        self.assertEqual(users.count(), 17)
        self.assertIn('já existia', out2.getvalue())
        call_command('seed_validation_users', remove=True, stdout=StringIO())
        self.assertEqual(users.count(), 0)
        self.assertFalse(Organization.objects.filter(name__startswith='[TESTE]').exists())
        self.assertTrue(Organization.objects.filter(pk=self.org.pk).exists())      # escritório real intocado

    def test_recusa_em_producao(self):
        from django.core.management.base import CommandError
        with self.settings(DJANGO_ENV='production'), self.assertRaises(CommandError):
            call_command('seed_validation_users', stdout=StringIO())


class StaffManagementTests(Base):
    """CAD-170: a TI cria e ajusta as contas da equipe (TI, Financeiro, Fiscal)."""

    def test_ti_cria_conta_sem_senha_e_envia_link(self):
        ti = self.as_(self.ti)
        body = {'email': 'Nova@Cadrius.ia.br', 'first_name': 'Nova', 'last_name': 'Pessoa', 'areas': ['fiscal'], 'reason': 'Contratação do fiscal'}
        with mock.patch('accounts.password_reset.send_reset_email') as send:
            res = ti.post('/api/v1/backoffice/staff/', body, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['areas'], ['fiscal'])
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.get(email='nova@cadrius.ia.br')
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        send.assert_called_once()
        self.assertTrue(AuditEvent.objects.filter(action='backoffice.action', changes__action='staff_created').exists())
        self.assertEqual(ti.post('/api/v1/backoffice/staff/', body, format='json').status_code, 400)          # e-mail repetido

    def test_validacoes_e_so_ti(self):
        ti = self.as_(self.ti)
        for bad in ({'email': 'x', 'areas': ['ti']}, {'email': 'a@b.com', 'areas': []}, {'email': 'a@b.com', 'areas': ['admin']},
                    {'email': 'a@b.com', 'areas': 'ti'}):
            self.assertEqual(ti.post('/api/v1/backoffice/staff/', {**bad, 'reason': REASON}, format='json').status_code, 400, bad)
        self.assertEqual(ti.post('/api/v1/backoffice/staff/', {'email': 'a@b.com', 'areas': ['ti']}, format='json').status_code, 400)  # sem motivo
        self.assertEqual(self.as_(self.fin).get('/api/v1/backoffice/staff/').status_code, 403)
        emails = [r['email'] for r in ti.get('/api/v1/backoffice/staff/').json()]
        self.assertIn('fin@cadrius.ia.br', emails)
        self.assertNotIn('dono@alfa.com', emails)

    def test_mudar_areas_e_tirar_da_equipe(self):
        ti = self.as_(self.ti)
        url = f'/api/v1/backoffice/staff/{self.fin.pk}/'
        self.assertEqual(ti.patch(url, {'areas': ['financeiro', 'fiscal'], 'reason': REASON}, format='json').json()['areas'],
                         ['financeiro', 'fiscal'])
        RefreshToken.for_user(self.fin)
        res = ti.patch(url, {'areas': [], 'reason': 'Saiu da empresa hoje'}, format='json').json()
        self.assertEqual((res['areas'], res['sessoes_encerradas']), ([], 1))
        self.fin.refresh_from_db()
        self.assertFalse(self.fin.is_staff)

    def test_protecoes(self):
        ti = self.as_(self.ti)
        self.assertEqual(ti.patch(f'/api/v1/backoffice/staff/{self.ti.pk}/', {'areas': ['financeiro'], 'reason': REASON},
                                  format='json').status_code, 400)                                           # não tira a própria TI
        root = staff('root@cadrius.ia.br', superuser=True)
        self.assertEqual(ti.patch(f'/api/v1/backoffice/staff/{root.pk}/', {'areas': ['ti'], 'reason': REASON},
                                  format='json').status_code, 400)                                           # superusuário


class FiscalTests(Base):
    """CAD-170: livro de recebimentos alimentado pelo Stripe, NF registrada pelo Fiscal e exportação ao contador."""

    def setUp(self):
        super().setUp()
        self.fiscal_user = staff('fiscal@cadrius.ia.br', 'fiscal')
        from billing.models import CreditPack
        self.pack = CreditPack.objects.create(name='200', credits=200, price_brl='99.00', is_active=True)
        self.org.stripe_subscription_id = 'sub_9'
        self.org.razao_social = 'Alfa Advogados Ltda'
        self.org.cnpj = '11.222.333/0001-81'
        self.org.save()

    def events(self):
        from billing.stripe_sync import apply_event
        invoice = {'type': 'invoice.paid', 'data': {'object': {'id': 'in_1', 'subscription': 'sub_9', 'amount_paid': 29900}}}
        apply_event(invoice)
        apply_event({**invoice, 'type': 'invoice.payment_succeeded'})          # mesmo pagamento, 2º evento: não duplica
        pack = {'type': 'checkout.session.completed', 'data': {'object': {
            'id': 'cs_pack', 'client_reference_id': str(self.org.pk), 'payment_status': 'paid', 'amount_total': 9900,
            'metadata': {'kind': 'credit_pack', 'pack_id': str(self.pack.pk)}}}}
        apply_event(pack)
        apply_event(pack)

    def test_livro_de_recebimentos_sem_duplicar(self):
        from billing.models import Payment
        self.events()
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(sorted(Payment.objects.values_list('amount_cents', flat=True)), [9900, 29900])

    def test_api_resumo_permissao_e_nf(self):
        self.events()
        self.assertEqual(self.as_(self.fin).get('/api/v1/backoffice/fiscal/payments/').status_code, 403)
        fiscal = self.as_(self.fiscal_user)
        data = fiscal.get('/api/v1/backoffice/fiscal/payments/').json()
        self.assertEqual((data['resumo']['total_brl'], data['resumo']['nf_pendentes']), ('398.00', 2))
        row = next(r for r in data['resultados'] if r['tipo'] == 'subscription')
        self.assertEqual(row['tomador'], {'nome': 'Alfa Advogados Ltda', 'documento': '11.222.333/0001-81'})
        url = f"/api/v1/backoffice/fiscal/payments/{row['id']}/invoice/"
        self.assertEqual(fiscal.post(url, {'status': 'issued', 'reason': 'NF emitida'}, format='json').status_code, 400)  # sem número
        ok = fiscal.post(url, {'status': 'issued', 'number': '2026/00017', 'issued_at': '2026-10-05', 'reason': 'NF emitida'}, format='json')
        self.assertEqual(ok.json()['nf_numero'], '2026/00017')
        self.assertEqual(fiscal.get('/api/v1/backoffice/fiscal/payments/?status=pending').json()['resumo']['quantidade'], 1)
        self.assertEqual(fiscal.get('/api/v1/backoffice/fiscal/payments/?start=2026-13-01').status_code, 400)
        self.assertIn('fiscal', fiscal.get('/api/v1/backoffice/overview/').json())

    def test_exporta_csv_para_o_contador(self):
        self.events()
        res = self.as_(self.fiscal_user).get('/api/v1/backoffice/fiscal/payments/export.csv')
        self.assertEqual(res.status_code, 200)
        text = res.content.decode('utf-8-sig')
        self.assertIn('Tomador;CPF/CNPJ', text)
        self.assertIn('299,00', text)
        self.assertTrue(AuditEvent.objects.filter(action='data.export').exists())


class MediaAddonCourtesyTests(Base):
    """CAD-231: a Gestão libera o adicional de mídia com IA como cortesia."""

    def test_liga_com_prazo_e_desliga(self):
        from billing import addons
        url = f'/api/v1/backoffice/organizations/{self.org.pk}/actions/'
        fin = self.as_(self.fin)
        res = fin.post(url, {'action': 'media_addon_on', 'days': 30, 'reason': REASON}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()['adicional_midia']['ativo'])
        self.assertEqual(res.json()['adicional_midia']['origem'], 'cortesia')
        self.assertTrue(fin.get(f'/api/v1/backoffice/organizations/{self.org.pk}/').json()['adicional_midia']['ativo'])
        self.assertEqual(fin.post(url, {'action': 'media_addon_on', 'days': 999, 'reason': REASON}, format='json').status_code, 400)
        self.assertEqual(self.as_(self.ti).post(url, {'action': 'media_addon_on', 'reason': REASON}, format='json').status_code, 403)
        fin.post(url, {'action': 'media_addon_off', 'reason': REASON}, format='json')
        self.assertFalse(addons.media_ai_enabled(self.org))
