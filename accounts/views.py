
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.throttling import ScopedRateThrottle
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
    plan_credits_used,
)
from billing.models import MemberCreditUsage
from .models import OrganizationMembership
from .tenancy import resolve_request_tenant
from audit import service as audit_service
from .team_roles import MANAGE_TEAM_ROLES, get_active_membership

User = get_user_model()

class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Substitui a view de login padrão para usar o serializer customizado.
    """
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_login'


class ThrottledTokenRefreshView(TokenRefreshView):
    from accounts.session_tokens import SessionRefreshSerializer as serializer_class   # CAD-232: mantém o prazo
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
    POST /api/v1/auth/register/ — cadastro de pessoa física.
    Cria usuário + escritório pessoal (owner) e devolve access/refresh.
    """
    permission_classes = (permissions.AllowAny,)
    serializer_class = IndividualRegistrationSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_register'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        audit_service.log('auth.register', actor=membership.user, data_categories=['identificacao', 'contato'],
                          legal_basis='contrato')
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
        audit_service.log('user.updated', actor=request.user, changes={'fields': sorted(serializer.validated_data)},
                          data_categories=['identificacao', 'contato'], legal_basis='contrato')
        return Response(UserProfileSerializer(instance).data)


class ProfileImageView(APIView):
    """POST/DELETE /api/v1/auth/profile/imagem/<foto|capa>/ — foto e capa do perfil (CAD-230)."""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, kind):
        from accounts import profile_images
        try:
            profile_images.save(request.user, kind, request.FILES.get('arquivo') or request.FILES.get('profile_picture'))
        except profile_images.ImageError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        audit_service.log('user.updated', actor=request.user, changes={'fields': [f'imagem:{kind}']},
                          data_categories=['identificacao'], legal_basis='consentimento')
        return Response(UserProfileSerializer(request.user).data)

    def delete(self, request, kind):
        from accounts import profile_images
        try:
            profile_images.remove(request.user, kind)
        except profile_images.ImageError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserProfileSerializer(request.user).data)


class PublicProfileImageView(APIView):
    """GET /api/v1/publico/perfil/<token>/ — a imagem do perfil por link assinado (a tela e a barra do topo usam <img>)."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, token):
        from django.core import signing
        from django.http import FileResponse, Http404
        from accounts import profile_images
        try:
            data = profile_images.read_token(token)
        except signing.BadSignature as exc:
            raise Http404 from exc
        spec = profile_images.KINDS.get(data.get('k'))
        user = User.objects.filter(pk=data.get('u'), is_active=True).first() if spec else None
        field = getattr(user, spec['field'], None) if user else None
        if not field or field.name != data.get('n') or not field.storage.exists(field.name):
            raise Http404
        ctype = 'image/png' if field.name.endswith('.png') else 'image/jpeg'
        resp = FileResponse(field.storage.open(field.name, 'rb'), content_type=ctype)
        resp['Cache-Control'] = 'private, max-age=604800, immutable'    # o link muda quando a imagem muda
        resp['X-Content-Type-Options'] = 'nosniff'
        resp['Cross-Origin-Resource-Policy'] = 'cross-origin'
        return resp


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/ — altera a senha do utilizador autenticado.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit_service.log('auth.password.forced_change' if serializer.was_forced else 'auth.password.change', actor=request.user,
                          data_categories=['credenciais'])
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
        used_this_month = MemberCreditUsage.objects.filter(
            membership=OuterRef('pk'),
            billing_cycle_month=current_billing_month(),
        ).values('credits_used')[:1]
        return (
            OrganizationMembership.objects.filter(
                organization=tenant,
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
        # 'role' fica registado (não é dado pessoal) para a regra A7 (escalada de privilégio).
        audit_service.log('member.invited', target=membership, organization=membership.organization,
                          changes={'role': membership.role}, data_categories=['identificacao', 'contato'],
                          legal_basis='contrato')
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


def _ai_usage_by_kind(organization):
    """Pedidos à IA no mês, por atividade (sem conteúdo): ajuda a entender onde os créditos foram."""
    from django.db.models import Count
    from aigov.models import AIActionLog
    month = current_billing_month()
    labels = dict(AIActionLog.Kind.choices)
    rows = (AIActionLog.objects.filter(organization_id=organization.pk, success=True, created_at__date__gte=month)
            .values('kind').annotate(n=Count('id')).order_by('-n'))
    return [{'atividade': r['kind'], 'rotulo': labels.get(r['kind'], r['kind']), 'pedidos': r['n']} for r in rows]


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
        from billing.entitlements import effective_monthly_credits, purchased_credits_balance
        total = effective_monthly_credits(organization)
        usados = plan_credits_used(organization)
        distribuidos = distributed_credits(organization)
        return Response({
            'creditos_total': total,
            'creditos_usados': usados,
            'creditos_disponiveis': max(total - usados, 0),
            'creditos_distribuidos': distribuidos,
            'creditos_nao_distribuidos': max(total - distribuidos, 0),
            'creditos_avulsos': purchased_credits_balance(organization),
            'uso_por_atividade': _ai_usage_by_kind(organization),          # CAD-225
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
            .order_by('user__email')
        )

    def list(self, request, *args, **kwargs):
        # Nome é cifrado em repouso (CAD-152): o banco não ordena nem filtra por ele; ordenamos em Python (listas pequenas)
        # e a busca ``?q=`` usa o índice de tokens (parcial, sem acento) ou o e-mail.
        from django.db.models import Q
        from core.pii import filter_by_term
        qs = self.filter_queryset(self.get_queryset())
        term = (request.query_params.get('q') or '').strip()
        if term:
            by_name = filter_by_term(qs, 'user__name_idx', 'user.name', term)
            qs = by_name | qs.filter(Q(user__email__icontains=term))
        members = sorted(qs.distinct(), key=lambda m: ((m.user.first_name or '').casefold(),
                                                       (m.user.last_name or '').casefold(), m.user.email))
        return Response(self.get_serializer(members, many=True).data)


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
