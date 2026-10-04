from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from audit import service as audit
from backoffice.permissions import AREA_GROUPS


class Command(BaseCommand):
    help = 'Define as áreas da Gestão Cadrius de um membro da equipe. Ex.: cadrius_staff ana@cadrius.ia.br --areas ti,financeiro (vazio = remove).'

    def add_arguments(self, parser):
        parser.add_argument('email')
        parser.add_argument('--areas', default='', help='ti, financeiro (separadas por vírgula). Vazio remove o acesso.')

    def handle(self, email, areas, **options):
        user = get_user_model().objects.filter(email__iexact=email.strip()).first()
        if user is None:
            raise CommandError('Usuário não encontrado.')
        wanted = {a.strip() for a in areas.split(',') if a.strip()}
        unknown = wanted - set(AREA_GROUPS)
        if unknown:
            raise CommandError(f'Área desconhecida: {", ".join(sorted(unknown))}. Use: {", ".join(AREA_GROUPS)}.')
        for area, name in AREA_GROUPS.items():
            group, _ = Group.objects.get_or_create(name=name)
            (user.groups.add if area in wanted else user.groups.remove)(group)
        if wanted and not user.is_staff:
            user.is_staff = True
            user.save(update_fields=['is_staff'])
        audit.log('backoffice.action', actor_type='system', target=user, reason='áreas da equipe alteradas via comando',
                  changes={'action': 'set_areas', 'areas': sorted(wanted)})
        self.stdout.write(f'{user.email}: áreas = {", ".join(sorted(wanted)) or "nenhuma"}')
