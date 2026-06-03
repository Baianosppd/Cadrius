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
    initials = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'initials', 
            'phone', 'cpf', 'oab_number', 'oab_uf', 'practice_area', 'profile_picture'
        ]
        # Aqui removemos o read_only_fields = fields para permitir que o 
        # Front-end faça PUT/PATCH e atualize o perfil!
        read_only_fields = ['id', 'email', 'initials']

    def get_initials(self, obj):
        if obj.first_name and obj.last_name:
            return f"{obj.first_name[0]}{obj.last_name[0]}".upper()
        if obj.first_name:
            return obj.first_name[0].upper()
        if obj.email:
             return obj.email[0].upper()
        return "U"

class UserRegistrationSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True, required=True)
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    class Meta:
        model = User
        # Expondo os campos para o formulário de Registo no Front-end
        fields = (
            'id', 'email', 'password', 'first_name', 'last_name', 
            'cpf', 'phone', 'oab_number', 'oab_uf', 'practice_area'  
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
        oab_number=validated_data.get('oab_number', ''), 
        oab_uf=validated_data.get('oab_uf', ''),            
        practice_area=validated_data.get('practice_area', ''), 
    )
        return user
