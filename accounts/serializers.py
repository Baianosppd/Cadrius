from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

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