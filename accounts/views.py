
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from .serializers import (
    UserRegistrationSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    ChangePasswordSerializer,
    TeamMemberSerializer,
    TeamMemberInviteSerializer,
    CustomTokenObtainPairSerializer,
)
from .models import OrganizationMembership
from .team_roles import get_active_membership

User = get_user_model()

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Substitui a view de login padrão para usar o serializer customizado.
    """
    serializer_class = CustomTokenObtainPairSerializer

class RegisterUserView(generics.CreateAPIView):
    """
    Endpoint para registrar um novo usuário.
    """
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = UserRegistrationSerializer

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
        return (
            OrganizationMembership.objects.filter(
                organization=membership.organization,
                is_active=True,
            )
            .select_related('user')
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
