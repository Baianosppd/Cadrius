"""API dos grupos de acesso do escritório (CAD-223). Configuração só para dono/administrador; o catálogo
("o que cada acesso concede") é aberto a toda a equipe, para cada pessoa entender o que tem."""
from django.db import IntegrityError
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import access
from accounts.models import AccessGroup, OrganizationMembership
from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit


def group_json(g: AccessGroup, members=None) -> dict:
    return {'id': g.pk, 'nome': g.name, 'descricao': g.description, 'permissoes': access.clean(g.permissions),
            'membros': members if members is not None else g.members.filter(is_active=True).count(), 'atualizado_em': g.updated_at}


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def manager(self, request):
        m = get_active_membership(request.user)
        if m is None or m.role not in MANAGE_TEAM_ROLES:
            return None, Response({'detail': 'Só o dono ou administrador configura os acessos da equipe.'}, status=status.HTTP_403_FORBIDDEN)
        return m, None

    def read(self, request):
        name = str(request.data.get('nome') or '').strip()[:60]
        if not name:
            return None, Response({'detail': 'Dê um nome ao grupo.'}, status=status.HTTP_400_BAD_REQUEST)
        perms = request.data.get('permissoes')
        if not isinstance(perms, list):
            return None, Response({'detail': 'Envie a lista de permissões.'}, status=status.HTTP_400_BAD_REQUEST)
        unknown = [p for p in perms if p not in access.ALL]
        if unknown:
            return None, Response({'detail': f'Permissão desconhecida: {", ".join(map(str, unknown[:3]))}.'}, status=status.HTTP_400_BAD_REQUEST)
        return {'name': name, 'description': str(request.data.get('descricao') or '').strip()[:200],
                'permissions': access.clean(perms)}, None


class AccessCatalogView(_Base):
    """GET /api/v1/teams/access/catalog/ — módulos, o que cada nível concede, extras, modelos e regras."""

    def get(self, request):
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        return Response({**access.catalog(), 'meu_acesso': access.summary(m)})


class AccessGroupsView(_Base):
    def get(self, request):
        m, err = self.manager(request)
        if err:
            return err
        return Response([group_json(g) for g in AccessGroup.objects.filter(organization=m.organization)])

    def post(self, request):
        m, err = self.manager(request)
        if err:
            return err
        preset = access.PRESETS.get(str(request.data.get('modelo') or ''))
        if preset:
            data = {'name': preset['nome'], 'description': preset['descricao'], 'permissions': access.clean(preset['permissoes'])}
        else:
            data, err = self.read(request)
            if err:
                return err
        try:
            g = AccessGroup.objects.create(organization=m.organization, created_by=request.user, **data)
        except IntegrityError:
            return Response({'detail': 'Já existe um grupo com esse nome.'}, status=status.HTTP_400_BAD_REQUEST)
        audit.log('team.access_group_saved', actor=request.user, organization=m.organization, target_type='access_group',
                  target_id=str(g.pk), changes={'nome': g.name, 'permissoes': g.permissions})
        return Response(group_json(g, 0), status=status.HTTP_201_CREATED)


class AccessGroupDetailView(_Base):
    def get_obj(self, m, pk):
        return AccessGroup.objects.filter(organization=m.organization, pk=pk).first()

    def patch(self, request, pk):
        m, err = self.manager(request)
        if err:
            return err
        g = self.get_obj(m, pk)
        if g is None:
            return Response({'detail': 'Grupo não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        data, err = self.read(request)
        if err:
            return err
        before = list(g.permissions)
        for k, v in data.items():
            setattr(g, k, v)
        try:
            g.save()
        except IntegrityError:
            return Response({'detail': 'Já existe um grupo com esse nome.'}, status=status.HTTP_400_BAD_REQUEST)
        audit.log('team.access_group_saved', actor=request.user, organization=m.organization, target_type='access_group',
                  target_id=str(g.pk), changes={'nome': g.name, 'antes': before, 'depois': g.permissions})
        return Response(group_json(g))

    def delete(self, request, pk):
        m, err = self.manager(request)
        if err:
            return err
        g = self.get_obj(m, pk)
        if g is None:
            return Response({'detail': 'Grupo não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        audit.log('team.access_group_deleted', actor=request.user, organization=m.organization, target_type='access_group',
                  target_id=str(g.pk), changes={'nome': g.name, 'membros': g.members.count()})
        g.delete()                                       # membros voltam às regras do cargo (SET_NULL)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberAccessView(_Base):
    """PATCH /api/v1/teams/members/<id>/access/ {grupo_id: n | null}."""

    def patch(self, request, pk):
        m, err = self.manager(request)
        if err:
            return err
        target = OrganizationMembership.objects.filter(organization=m.organization, pk=pk, is_active=True).select_related('user').first()
        if target is None:
            return Response({'detail': 'Membro não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        gid = request.data.get('grupo_id')
        group = None
        if gid not in (None, ''):
            group = AccessGroup.objects.filter(organization=m.organization, pk=gid).first()
            if group is None:
                return Response({'detail': 'Grupo não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
            if target.role in MANAGE_TEAM_ROLES:
                return Response({'detail': 'Dono e administrador têm acesso total; mude o cargo antes de colocar num grupo.'},
                                status=status.HTTP_400_BAD_REQUEST)
        before = target.access_group.name if target.access_group_id else None
        target.access_group = group
        target.save(update_fields=['access_group'])
        audit.log('team.access_assigned', actor=request.user, organization=m.organization, target_type='membership',
                  target_id=str(target.pk), changes={'antes': before, 'depois': group.name if group else None})
        from accounts.serializers import TeamMemberSerializer
        return Response(TeamMemberSerializer(target).data)
