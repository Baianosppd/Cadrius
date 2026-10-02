
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .registration import (
    CompanyRegistrationSerializer,
    IndividualRegistrationSerializer,
    registration_response,
)
from .serializers import (
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    ChangePasswordSerializer,
    TeamMemberSerializer,
    TeamMemberInviteSerializer,
    MemberCreditLimitSerializer,
    FuncionarioSerializer,
    CustomTokenObtainPairSerializer,
)
from django.db.models import OuterRef, Subquery
from billing.credits import (
    current_billing_month,
    distributed_credits,
    organization_credits_used,
)
from billing.models import MemberCreditUsage
from .models import OrganizationMembership
from .team_roles import MANAGE_TEAM_ROLES, get_active_membership

User = get_user_model()

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Substitui a view de login padrão para usar o serializer customizado.
    """
    serializer_class = CustomTokenObtainPairSerializer

class RegisterUserView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/ — cadastro de pessoa física.
    Cria usuário + escritório pessoal (owner) e devolve access/refresh.
    """
    permission_classes = (permissions.AllowAny,)
    serializer_class = IndividualRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(registration_response(membership), status=status.HTTP_201_CREATED)


class RegisterCompanyView(RegisterUserView):
    """
    POST /api/v1/auth/register/empresa/ — cadastro de empresa.
    Cria escritório + gerente responsável (owner) e devolve access/refresh.
    """
    serializer_class = CompanyRegistrationSerializer

class GetUserProfileView(generics.RetrieveAPIView):
    """
    Endpoint para obter os dados do usuário autenticado.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user


class UpdateUserProfileView(generics.UpdateAPIView):
    """
    PATCH /api/v1/auth/profile/ — atualiza nome, telefone e OAB do utilizador autenticado.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserProfileUpdateSerializer
    http_method_names = ['patch', 'options', 'head']

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(UserProfileSerializer(instance).data)


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/ — altera a senha do utilizador autenticado.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'detail': 'Senha alterada com sucesso.'},
            status=status.HTTP_200_OK,
        )


class TeamMemberListCreateView(generics.ListCreateAPIView):
    """
    GET /api/v1/teams/members/ — lista membros do escritório do utilizador.
    POST /api/v1/teams/members/ — convida funcionário por e-mail.
    """
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TeamMemberInviteSerializer
        return TeamMemberSerializer

    def get_queryset(self):
        membership = get_active_membership(self.request.user)
        if membership is None:
            return OrganizationMembership.objects.none()
        used_this_month = MemberCreditUsage.objects.filter(
            membership=OuterRef('pk'),
            billing_cycle_month=current_billing_month(),
        ).values('credits_used')[:1]
        return (
            OrganizationMembership.objects.filter(
                organization=membership.organization,
                is_active=True,
            )
            .select_related('user')
            .annotate(creditos_usados=Subquery(used_this_month))
            .order_by('joined_at')
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(
            TeamMemberSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


class MemberCreditLimitView(APIView):
    """
    PATCH /api/v1/teams/members/{id}/credits/
    Define a cota mensal de créditos do membro (só OWNER/ADMIN). null = sem cota.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        requester = get_active_membership(request.user)
        if requester is None or requester.role not in MANAGE_TEAM_ROLES:
            return Response(
                {'detail': 'Sem permissão para gerir créditos da equipa.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        membership = (
            OrganizationMembership.objects.select_related('user', 'organization__plan')
            .filter(pk=pk, organization=requester.organization, is_active=True)
            .first()
        )
        if membership is None:
            return Response({'detail': 'Membro não encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MemberCreditLimitSerializer(
            data=request.data,
            context={'membership': membership},
        )
        serializer.is_valid(raise_exception=True)
        membership.credit_limit = serializer.validated_data['creditos_limite']
        membership.save(update_fields=['credit_limit'])
        return Response(TeamMemberSerializer(membership).data)


class TeamCreditsSummaryView(APIView):
    """
    GET /api/v1/teams/credits/
    Créditos gerais do escritório no mês corrente.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        membership = get_active_membership(request.user)
        if membership is None:
            return Response(
                {'detail': 'Utilizador sem organização ativa.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        organization = membership.organization
        total = organization.plan.max_ai_extractions
        usados = organization_credits_used(organization)
        distribuidos = distributed_credits(organization)
        return Response({
            'creditos_total': total,
            'creditos_usados': usados,
            'creditos_disponiveis': max(total - usados, 0),
            'creditos_distribuidos': distribuidos,
            'creditos_nao_distribuidos': max(total - distribuidos, 0),
        })


class FuncionariosListView(generics.ListAPIView):
    """
    GET /api/v1/funcionarios/
    Funcionários ativos do escritório da sessão (dropdown Responsável / NewTask).
    """
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None
    serializer_class = FuncionarioSerializer

    def get_queryset(self):
        membership = get_active_membership(self.request.user)
        if membership is None:
            return OrganizationMembership.objects.none()
        return (
            OrganizationMembership.objects.filter(
                organization=membership.organization,
                is_active=True,
            )
            .select_related('user')
            .order_by('user__first_name', 'user__last_name', 'user__email')
        )


class PermissionGroupListView(generics.ListAPIView):
    """
    GET /api/v1/teams/permission-groups/
    Catálogo de grupos de permissão para a aba Gestão de Equipe.
    """
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        from .permission_groups import list_permission_groups
        return Response(list_permission_groups())
