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
    """
    Serializer simplificado para retornar os dados do usuário logado.
    """
    initials = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'initials']
        read_only_fields = fields

    def get_initials(self, obj):
        """Calcula as iniciais do usuário."""
        if obj.first_name and obj.last_name:
            return f"{obj.first_name[0]}{obj.last_name[0]}".upper()
        if obj.first_name:
            return obj.first_name[0].upper()
        if obj.email:
             return obj.email[0].upper()
        return "U" # Fallback para 'Usuário'

class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer para criação de um novo usuário.
    Assume que o 'email' será usado como 'username' para login.
    """
    email = serializers.EmailField(write_only=True, required=True, label="E-mail")
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'first_name', 'last_name')
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def validate(self, data):
        if User.objects.filter(username=data['email']).exists():
            raise serializers.ValidationError({"email": "Este e-mail já está sendo usado."})
        data['username'] = data['email']
        return data

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        return user