from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from .models import OrganizationMembership

User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Personaliza o serializer de login para usar 'email' como campo de usuário
    e para incluir dados customizados no token, se necessário.
    """
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Adicione claims customizados aqui (ex: 'first_name')
        token['first_name'] = user.first_name
        return token

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        return token

class UserProfileSerializer(serializers.ModelSerializer):
    """GET /api/v1/auth/user/ — somente leitura."""

    initials = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'initials',
            'phone', 'cpf', 'oab_number', 'oab_uf', 'practice_area', 'profile_picture',
        ]
        read_only_fields = fields

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
        return data

    def save(self, **kwargs):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user

class UserRegistrationSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True, required=True)
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        # Expondo os campos para o formulário de Registo no Front-end
        fields = (
            'id', 'email', 'password', 'first_name', 'last_name', 
            'cpf', 'phone'
        )
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def validate(self, data):
        if User.objects.filter(username=data['email']).exists():
            raise serializers.ValidationError({"email": "Este e-mail já está a ser utilizado."})
        data['username'] = data['email']
        return data

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            cpf=validated_data.get('cpf', ''),
            phone=validated_data.get('phone', ''),
        )
        return user


class TeamMemberSerializer(serializers.ModelSerializer):
    """GET/POST /api/v1/teams/members/ — representação de membro da equipa."""

    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    role = serializers.SerializerMethodField()

    class Meta:
        model = OrganizationMembership
        fields = ['id', 'email', 'first_name', 'last_name', 'role', 'joined_at']
        read_only_fields = fields

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