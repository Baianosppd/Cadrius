from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import OrganizationMembership

User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Personaliza o serializer de login para usar 'email' como campo de usuário
    e para incluir dados customizados no token, se necessário.
    """
    @classmethod
    def get_token(cls, user):
        # Só o identificador padrão (user_id): nome/e-mail no JWT ficariam legíveis (base64) por terceiros.
        return super().get_token(user)

    def validate(self, attrs):
        data = super().validate(attrs)  # levanta 401 (e dispara user_login_failed) se inválido
        from accounts.team_roles import get_active_membership
        from audit import service
        membership = get_active_membership(self.user)
        service.log(
            'auth.login.success', actor=self.user,
            organization=membership.organization if membership else None,
            data_categories=['identificacao'], legal_basis='contrato',
        )
        return data

class UserProfileSerializer(serializers.ModelSerializer):
    """GET /api/v1/auth/user/ — somente leitura."""

    initials = serializers.SerializerMethodField()
    organization = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'initials',
            'phone', 'cpf', 'oab_number', 'oab_uf', 'practice_area', 'profile_picture',
            'organization', 'role', 'is_staff',
        ]
        read_only_fields = fields

    def _membership(self, obj):
        from .team_roles import get_active_membership
        return get_active_membership(obj)

    def get_organization(self, obj):
        membership = self._membership(obj)
        if membership is None:
            return None
        org = membership.organization
        return {'id': str(org.id), 'name': org.name, 'account_type': org.account_type}

    def get_role(self, obj):
        """Papel no escritório ativo (OWNER/ADMIN/MEMBER/VIEWER) — o front usa para mostrar/ocultar telas."""
        membership = self._membership(obj)
        return membership.role if membership else None

    def get_initials(self, obj):
        if obj.first_name and obj.last_name:
            return f"{obj.first_name[0]}{obj.last_name[0]}".upper()
        if obj.first_name:
            return obj.first_name[0].upper()
        if obj.email:
            return obj.email[0].upper()
        return "U"


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """PATCH /api/v1/auth/profile/ — atualização parcial do perfil."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'oab_number']
        extra_kwargs = {
            'first_name': {'required': False},
            'last_name': {'required': False},
            'phone': {'required': False},
            'oab_number': {'required': False},
        }


class ChangePasswordSerializer(serializers.Serializer):
    """POST /api/v1/auth/change-password/ — troca de senha do utilizador autenticado."""

    current_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )
    new_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
    )

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Senha atual incorreta.')
        return value

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': 'As senhas não coincidem.'},
            )
        if data['current_password'] == data['new_password']:
            raise serializers.ValidationError(
                {'new_password': 'A nova senha deve ser diferente da senha atual.'},
            )
        # Aplica AUTH_PASSWORD_VALIDATORS (antes ignorados fora do admin).
        try:
            validate_password(data['new_password'], self.context['request'].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'new_password': list(exc.messages)})
        return data

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user

class TeamMemberSerializer(serializers.ModelSerializer):
    """GET/POST /api/v1/teams/members/ — representação de membro da equipa."""

    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    role = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    creditos_usados = serializers.SerializerMethodField()
    creditos_limite = serializers.IntegerField(source='credit_limit', read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = [
            'id',
            'email',
            'first_name',
            'last_name',
            'role',
            'status',
            'creditos_usados',
            'creditos_limite',
            'joined_at',
        ]
        read_only_fields = fields

    def get_role(self, obj):
        from .team_roles import role_to_frontend
        return role_to_frontend(obj.role)

    def get_status(self, obj):
        return 'ativo' if obj.is_active else 'inativo'

    def get_creditos_usados(self, obj):
        used = getattr(obj, 'creditos_usados', None)
        if used is not None:
            return used
        from billing.credits import member_credits_used
        return member_credits_used(obj)


class MemberCreditLimitSerializer(serializers.Serializer):
    """PATCH /api/v1/teams/members/{id}/credits/ — cota mensal do membro (null = sem cota)."""

    creditos_limite = serializers.IntegerField(min_value=0, allow_null=True)

    def validate_creditos_limite(self, value):
        if value is None:
            return value
        from billing.credits import distributed_credits

        membership = self.context['membership']
        organization = membership.organization
        plan_total = organization.plan.max_ai_extractions
        others = distributed_credits(organization, exclude_membership_id=membership.pk)
        if others + value > plan_total:
            raise serializers.ValidationError(
                f'Cota excede o total do plano. Disponível para distribuir: {max(plan_total - others, 0)}.'
            )
        return value


class FuncionarioSerializer(serializers.ModelSerializer):
    """
    GET /api/v1/funcionarios/ — lista para dropdowns (ex.: Responsável na NewTask).
    ``user_id`` é o UUID a enviar em ``responsavel`` no POST /api/v1/tasks/.
    """

    user_id = serializers.UUIDField(source='user.id', read_only=True)
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source='user.email', read_only=True)
    role = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationMembership
        fields = ['user_id', 'name', 'email', 'role']
        read_only_fields = fields

    def get_name(self, obj):
        full = f"{obj.user.first_name or ''} {obj.user.last_name or ''}".strip()
        return full or obj.user.email or obj.user.username

    def get_role(self, obj):
        from .team_roles import role_to_frontend
        return role_to_frontend(obj.role)


class TeamMemberInviteSerializer(serializers.Serializer):
    """POST /api/v1/teams/members/ — convite de funcionário."""

    email = serializers.EmailField()
    role = serializers.CharField()

    def validate_email(self, value):
        return value.strip().lower()

    def validate_role(self, value):
        from .team_roles import resolve_backend_role
        backend_role = resolve_backend_role(value)
        if backend_role is None:
            raise serializers.ValidationError('Cargo inválido.')
        return backend_role

    def validate(self, data):
        from .team_roles import MANAGE_TEAM_ROLES, get_active_membership
        from rest_framework.exceptions import PermissionDenied

        inviter_membership = get_active_membership(self.context['request'].user)
        if inviter_membership is None:
            raise serializers.ValidationError({
                'detail': (
                    'A sua conta autenticada não pertence a nenhum escritório. '
                    'Associe-se a uma organização antes de convidar membros.'
                ),
            })
        if inviter_membership.role not in MANAGE_TEAM_ROLES:
            raise PermissionDenied(
                'Apenas donos ou administradores do escritório podem convidar membros.',
            )

        # Só OWNER concede OWNER (um ADMIN podia convidar-se a si/colegas como dono).
        if data['role'] == 'OWNER' and inviter_membership.role != 'OWNER':
            raise PermissionDenied('Apenas o dono do escritório pode conceder o cargo de dono.')

        self.context['inviter_membership'] = inviter_membership
        return data

    def create(self, validated_data):
        organization = self.context['inviter_membership'].organization
        active_count = organization.members.filter(is_active=True).count()
        if active_count >= organization.plan.max_users:
            raise serializers.ValidationError(
                {'email': 'Limite de utilizadores do plano atingido.'},
            )

        email = validated_data['email']
        role = validated_data['role']
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create(username=email, email=email)
            user.set_unusable_password()
            user.save()

        membership = OrganizationMembership.objects.filter(
            user=user,
            organization=organization,
        ).first()
        if membership is not None:
            if membership.is_active:
                raise serializers.ValidationError(
                    {'email': 'Este utilizador já pertence à equipa.'},
                )
            membership.is_active = True
            membership.role = role
            membership.save(update_fields=['is_active', 'role'])
            return membership

        return OrganizationMembership.objects.create(
            user=user,
            organization=organization,
            role=role,
        )