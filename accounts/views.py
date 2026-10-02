
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.throttling import ScopedRateThrottle
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
from .tenancy import resolve_request_tenant
from audit import service as audit_service

User = get_user_model()

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Substitui a view de login padrão para usar o serializer customizado.
    """
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_login'


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_refresh'


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/ — revoga o refresh token (blacklist).
    Body: {"refresh": "<token>"}. Sem isto o token roubado continuava válido até expirar.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            return Response({'detail': 'Campo "refresh" é obrigatório.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response({'detail': 'Token inválido ou já revogado.'}, status=status.HTTP_400_BAD_REQUEST)
        audit_service.log('auth.logout')
        return Response(status=status.HTTP_205_RESET_CONTENT)


class RegisterUserView(generics.CreateAPIView):
    """
    Endpoint para registrar um novo usuário.
    """
    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = UserRegistrationSerializer

    def perform_create(self, serializer):
        user = serializer.save()
        audit_service.log('auth.register', actor=user, data_categories=['identificacao', 'contato'],
                          legal_basis='contrato')
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_register'

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
        audit_service.log('user.updated', actor=request.user, changes={'fields': sorted(serializer.validated_data)},
                          data_categories=['identificacao', 'contato'], legal_basis='contrato')
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
        audit_service.log('auth.password.change', actor=request.user)
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
        tenant = resolve_request_tenant(self.request)
        if tenant is None:
            return OrganizationMembership.objects.none()
        return (
            OrganizationMembership.objects.filter(
                organization=tenant,
                is_active=True,
            )
            .select_related('user')
            .order_by('joined_at')
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        # 'role' fica registado (não é dado pessoal) para a regra A7 (escalada de privilégio).
        audit_service.log('member.invited', target=membership, organization=membership.organization,
                          changes={'role': membership.role}, data_categories=['identificacao', 'contato'],
                          legal_basis='contrato')
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
