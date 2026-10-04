"""Cria (ou remove) as contas de VALIDAÇÃO no ambiente de teste — CAD-169.

    python manage.py seed_validation_users             # cria o que falta e imprime as senhas UMA vez
    python manage.py seed_validation_users --reset-passwords
    python manage.py seed_validation_users --remove    # apaga tudo o que este comando criou

Recusa rodar em produção (DJANGO_ENV=production). Todos os e-mails são @teste.cadrius.ia.br e os escritórios começam com
"[TESTE]", para nunca se confundirem com clientes. Roteiro do que validar com cada conta: docs/VALIDACAO_STAGING.md.
"""
from __future__ import annotations

import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Organization, OrganizationMembership
from audit import service as audit
from backoffice.permissions import AREA_GROUPS
from billing.models import SubscriptionPlan

DOMAIN = 'teste.cadrius.ia.br'
PREFIX = '[TESTE] '

# e-mail (sem domínio) → (nome, staff_areas | None, escritório | None, papel)
STAFF = {
    'gestao.ti': ('TI', ['ti'], None, None),
    'gestao.financeiro': ('Financeiro', ['financeiro'], None, None),
    'gestao.completa': ('Gestão completa', ['ti', 'financeiro'], None, None),
    'gestao.semarea': ('Equipe sem área', [], None, None),
}
# escritório → (estado, dias: trial restante ou dias em atraso, plano preferido)
OFFICES = {
    'Ativo': ('active', None, 'PRO'),
    'Em teste': ('trialing', 3, 'PRO'),
    'Teste vencido': ('trialing', -2, 'START'),
    'Pagamento pendente': ('past_due', 3, 'START'),
    'Restrito': ('past_due', 10, 'START'),
    'Suspenso': ('past_due', 20, 'START'),
    'Cancelado': ('canceled', None, 'START'),
}
MEMBERS = {
    'dono': ('Dono', 'Ativo', 'OWNER'),
    'admin': ('Administradora', 'Ativo', 'ADMIN'),
    'advogado': ('Advogado', 'Ativo', 'MEMBER'),
    'leitura': ('Leitura', 'Ativo', 'VIEWER'),
    'dono.trial': ('Dono em teste', 'Em teste', 'OWNER'),
    'dono.vencido': ('Dono teste vencido', 'Teste vencido', 'OWNER'),
    'dono.pendente': ('Dono pendente', 'Pagamento pendente', 'OWNER'),
    'dono.restrito': ('Dono restrito', 'Restrito', 'OWNER'),
    'dono.suspenso': ('Dono suspenso', 'Suspenso', 'OWNER'),
    'dono.cancelado': ('Dono cancelado', 'Cancelado', 'OWNER'),
}


def _password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = ''.join(secrets.choice(alphabet) for _ in range(14))
    return f'{core}-{secrets.randbelow(90) + 10}!'   # cumpre as regras de senha (maiúscula, número, símbolo, tamanho)


class Command(BaseCommand):
    help = 'Cria/remove as contas de validação (equipe e escritórios [TESTE]) no ambiente de teste. Nunca em produção.'

    def add_arguments(self, parser):
        parser.add_argument('--remove', action='store_true', help='Apaga as contas e escritórios de validação.')
        parser.add_argument('--reset-passwords', action='store_true', help='Gera senha nova também para as contas que já existem.')

    def handle(self, *args, remove=False, reset_passwords=False, **options):
        if getattr(settings, 'DJANGO_ENV', 'development') == 'production':
            raise CommandError('Recusado: DJANGO_ENV=production. Contas de validação só no ambiente de teste.')
        if remove:
            return self._remove()
        plans = {p.tier: p for p in SubscriptionPlan.objects.filter(is_active=True)}
        if not plans:
            raise CommandError('Nenhum plano ativo. Rode antes: python manage.py seed_plans --apply')
        with transaction.atomic():
            orgs = {name: self._office(name, *spec, plans) for name, spec in OFFICES.items()}
            rows = [self._user(local, label, areas=areas, reset=reset_passwords) for local, (label, areas, _, _) in STAFF.items()]
            for local, (label, office, role) in MEMBERS.items():
                rows.append(self._user(local, label, org=orgs[office], role=role, reset=reset_passwords))
        audit.log('backoffice.action', actor_type='system', reason='contas de validação criadas no ambiente de teste',
                  changes={'action': 'seed_validation_users', 'contas': len(rows)})
        width = max(len(r[0]) for r in rows)
        self.stdout.write(self.style.WARNING('\nGuarde estas senhas agora (não serão mostradas de novo). Login: e-mail + senha.\n'))
        for email, info, password in rows:
            self.stdout.write(f'{email.ljust(width)}  {password or "(já existia — senha mantida)":32}  {info}')
        self.stdout.write('\nEquipe: no 1º login a Gestão pede o cadastro do MFA (Google/Microsoft Authenticator). '
                          'Roteiro: docs/VALIDACAO_STAGING.md')

    def _office(self, name, state, days, tier, plans):
        now = timezone.now()
        plan = plans.get(tier) or next(iter(plans.values()))
        org, _ = Organization.objects.get_or_create(name=f'{PREFIX}{name}', defaults={'plan': plan, 'nome_fantasia': f'{PREFIX}{name}'})
        org.plan, org.subscription_status, org.is_active = plan, state, True
        org.trial_ends_at = now + timedelta(days=days) if state == 'trialing' else None
        org.past_due_since = now - timedelta(days=days) if state == 'past_due' else None
        org.current_period_end = now + timedelta(days=20) if state == 'active' else None
        org.save()
        return org

    def _user(self, local, label, *, areas=None, org=None, role=None, reset=False):
        User = get_user_model()
        email = f'{local}@{DOMAIN}'
        user = User.objects.filter(email=email).first()
        password = None
        if user is None:
            password = _password()
            user = User.objects.create_user(username=email, email=email, password=password, first_name=label, last_name='Teste')
        elif reset:
            password = _password()
            user.set_password(password)
            user.save(update_fields=['password'])
        if areas is not None:
            user.is_staff = True
            user.save(update_fields=['is_staff'])
            for area, group_name in AREA_GROUPS.items():
                group, _ = Group.objects.get_or_create(name=group_name)
                (user.groups.add if area in areas else user.groups.remove)(group)
            info = f'equipe Cadrius — áreas: {", ".join(areas) or "nenhuma"}'
        else:
            OrganizationMembership.objects.update_or_create(user=user, organization=org, defaults={'role': role, 'is_active': True})
            info = f'{org.name} — {role}'
        return email, info, password

    def _remove(self):
        User = get_user_model()
        with transaction.atomic():
            users = User.objects.filter(email__endswith=f'@{DOMAIN}')
            n_users = users.count()
            users.delete()
            orgs = Organization.objects.filter(name__startswith=PREFIX)
            n_orgs = orgs.count()
            orgs.delete()
        audit.log('backoffice.action', actor_type='system', reason='contas de validação removidas',
                  changes={'action': 'seed_validation_users_remove', 'contas': n_users, 'escritorios': n_orgs})
        self.stdout.write(f'Removidos: {n_users} contas e {n_orgs} escritórios de validação.')
