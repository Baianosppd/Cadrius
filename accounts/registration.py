"""Cadastro público: pessoa física (advogado) e empresa (escritório + gerente responsável)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from billing.models import SubscriptionPlan

from .models import Organization, OrganizationMembership
from .validators import format_cnpj, format_cpf, is_valid_cnpj, is_valid_cpf, only_digits

User = get_user_model()

UF_CHOICES = [
    'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA',
    'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
]
AREA_ATUACAO_CHOICES = [
    ('civil', 'Direito Civil'),
    ('penal', 'Direito Penal'),
    ('trabalhista', 'Direito Trabalhista'),
    ('tributario', 'Direito Tributário'),
    ('empresarial', 'Direito Empresarial'),
    ('familia', 'Direito de Família'),
    ('previdenciario', 'Direito Previdenciário'),
    ('outra', 'Outra'),
]
TIPO_SOCIEDADE_CHOICES = [
    ('LTDA', 'Sociedade Limitada (LTDA)'),
    ('SA', 'Sociedade Anônima (S.A.)'),
    ('EIRELI', 'EIRELI'),
    ('MEI', 'MEI'),
]
REGIME_TRIBUTARIO_CHOICES = [
    ('SIMPLES_NACIONAL', 'Simples Nacional'),
    ('LUCRO_PRESUMIDO', 'Lucro Presumido'),
    ('LUCRO_REAL', 'Lucro Real'),
]


def _split_name(nome_completo):
    parts = nome_completo.split()
    return parts[0], ' '.join(parts[1:])


class LegalAcceptanceMixin(serializers.Serializer):
    """Aceite dos documentos legais vigentes (LGPD): versão exata exibida ao utilizador."""

    LEGAL_FIELDS = {
        'terms': 'accepted_terms_version',
        'privacy': 'accepted_privacy_version',
        'ciencia': 'accepted_ciencia_version',
    }
    accepted_terms_version = serializers.CharField(write_only=True, required=False)
    accepted_privacy_version = serializers.CharField(write_only=True, required=False)
    accepted_ciencia_version = serializers.CharField(write_only=True, required=False)

    def _validate_legal_acceptance(self, data):
        from privacy import consent

        self._documents_to_record = []
        if not consent.acceptance_required():
            return
        errors = {}
        for doc in consent.current_documents(consent.REQUIRED_KINDS):
            field = self.LEGAL_FIELDS[doc.kind]
            if data.get(field) != doc.version:
                errors[field] = f'É necessário aceitar a versão vigente ({doc.version}) de: {doc.title}.'
            else:
                self._documents_to_record.append(doc)
        if errors:
            raise serializers.ValidationError(errors)

    def _record_legal_acceptance(self, user):
        from privacy import consent

        for doc in getattr(self, '_documents_to_record', []):
            consent.record_consent(user, doc, method='checkbox')


class PersonDataSerializer(serializers.Serializer):
    """Dados de quem vai fazer login (advogado ou gerente responsável)."""

    nome_completo = serializers.CharField(max_length=300)
    cpf = serializers.CharField(max_length=14)
    email = serializers.EmailField()
    senha = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate_nome_completo(self, value):
        value = ' '.join(value.split())
        if not value:
            raise serializers.ValidationError('Informe o nome completo.')
        return value

    def validate_cpf(self, value):
        if not is_valid_cpf(value):
            raise serializers.ValidationError('CPF inválido.')
        formatted = format_cpf(value)
        if User.objects.filter(cpf__in=[formatted, only_digits(value)]).exists():
            raise serializers.ValidationError('Este CPF já está cadastrado.')
        return formatted

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists() or User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Este e-mail já está cadastrado.')
        return value

    def validate(self, data):
        first_name, last_name = _split_name(data['nome_completo'])
        candidate = User(username=data['email'], email=data['email'], first_name=first_name, last_name=last_name)
        try:
            validate_password(data['senha'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'senha': list(exc.messages)})
        return data


def _active_plan(plan_id):
    plan = SubscriptionPlan.objects.filter(pk=plan_id, is_active=True).first()
    if plan is None:
        raise serializers.ValidationError('Plano inválido.')
    return plan


def _start_trial(organization):
    """CAD-119: o plano escolhido (pago ou não) só vale integralmente depois do pagamento; até lá, limites do trial."""
    from billing.entitlements import start_trial
    start_trial(organization)
    organization.save(update_fields=['subscription_status', 'trial_ends_at'])


def _create_user(person, **extra):
    first_name, last_name = _split_name(person['nome_completo'])
    return User.objects.create_user(
        username=person['email'],
        email=person['email'],
        password=person['senha'],
        first_name=first_name,
        last_name=last_name,
        cpf=person['cpf'],
        **extra,
    )


class IndividualRegistrationSerializer(LegalAcceptanceMixin, PersonDataSerializer):
    """POST /api/v1/auth/register/ — pessoa física; cria a conta e o escritório pessoal."""

    oab_numero = serializers.CharField(max_length=20, required=False, allow_blank=True)
    oab_uf = serializers.ChoiceField(choices=UF_CHOICES, required=False, allow_blank=True)
    area_atuacao = serializers.ChoiceField(choices=AREA_ATUACAO_CHOICES, required=False, allow_blank=True)
    plano_id = serializers.IntegerField()

    def validate_plano_id(self, value):
        return _active_plan(value)

    def validate(self, data):
        data = super().validate(data)
        self._validate_legal_acceptance(data)
        return data

    @transaction.atomic
    def create(self, validated_data):
        plan = validated_data['plano_id']
        user = _create_user(
            validated_data,
            oab_number=validated_data.get('oab_numero') or None,
            oab_uf=validated_data.get('oab_uf') or None,
            practice_area=validated_data.get('area_atuacao') or None,
        )
        organization = Organization.objects.create(
            account_type='PESSOA_FISICA',
            name=validated_data['nome_completo'],
            plan=plan,
        )
        _start_trial(organization)
        membership = OrganizationMembership.objects.create(
            user=user,
            organization=organization,
            role='OWNER',
        )
        self._record_legal_acceptance(user)
        return membership


class ManagerSerializer(PersonDataSerializer):
    cargo = serializers.CharField(max_length=100, required=False, allow_blank=True)


class CompanyRegistrationSerializer(LegalAcceptanceMixin, serializers.Serializer):
    """POST /api/v1/auth/register/empresa/ — escritório + gerente responsável (owner)."""

    razao_social = serializers.CharField(max_length=255)
    nome_fantasia = serializers.CharField(max_length=255)
    cnpj = serializers.CharField(max_length=18)
    tipo_sociedade = serializers.ChoiceField(choices=TIPO_SOCIEDADE_CHOICES, required=False, allow_blank=True)
    porte_empresa = serializers.ChoiceField(choices=Organization.COMPANY_SIZE_CHOICES)
    regime_tributario = serializers.ChoiceField(choices=REGIME_TRIBUTARIO_CHOICES, required=False, allow_blank=True)

    cep = serializers.CharField(max_length=9, required=False, allow_blank=True)
    logradouro = serializers.CharField(max_length=255, required=False, allow_blank=True)
    numero = serializers.CharField(max_length=20, required=False, allow_blank=True)
    bairro = serializers.CharField(max_length=100, required=False, allow_blank=True)
    cidade = serializers.CharField(max_length=100, required=False, allow_blank=True)
    uf = serializers.ChoiceField(choices=UF_CHOICES, required=False, allow_blank=True)
    telefone_principal = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email_corporativo = serializers.EmailField(required=False, allow_blank=True)

    gerente = ManagerSerializer()
    plano_id = serializers.IntegerField()

    def validate_cnpj(self, value):
        if not is_valid_cnpj(value):
            raise serializers.ValidationError('CNPJ inválido.')
        formatted = format_cnpj(value)
        if Organization.objects.filter(cnpj__in=[formatted, only_digits(value)]).exists():
            raise serializers.ValidationError('Este CNPJ já está cadastrado.')
        return formatted

    def validate_cep(self, value):
        if not value:
            return value
        digits = only_digits(value)
        if len(digits) != 8:
            raise serializers.ValidationError('CEP inválido.')
        return f'{digits[:5]}-{digits[5:]}'

    def validate_plano_id(self, value):
        return _active_plan(value)

    def validate(self, data):
        self._validate_legal_acceptance(data)
        return data

    @transaction.atomic
    def create(self, validated_data):
        manager = validated_data['gerente']
        organization = Organization.objects.create(
            account_type='EMPRESA',
            name=validated_data['nome_fantasia'],
            razao_social=validated_data['razao_social'],
            nome_fantasia=validated_data['nome_fantasia'],
            cnpj=validated_data['cnpj'],
            company_type=validated_data.get('tipo_sociedade') or None,
            company_size=validated_data['porte_empresa'],
            tax_regime=validated_data.get('regime_tributario') or None,
            cep=validated_data.get('cep') or None,
            street=validated_data.get('logradouro') or None,
            number=validated_data.get('numero') or None,
            neighborhood=validated_data.get('bairro') or None,
            city=validated_data.get('cidade') or None,
            state_uf=validated_data.get('uf') or None,
            main_phone=validated_data.get('telefone_principal') or None,
            corporate_email=validated_data.get('email_corporativo') or None,
            plan=validated_data['plano_id'],
        )
        _start_trial(organization)
        user = _create_user(manager)
        membership = OrganizationMembership.objects.create(
            user=user,
            organization=organization,
            role='OWNER',
            job_title=manager.get('cargo', ''),
        )
        self._record_legal_acceptance(user)
        return membership


def registration_response(membership):
    from .serializers import CustomTokenObtainPairSerializer

    user = membership.user
    organization = membership.organization
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    return {
        'user': {
            'id': str(user.id),
            'email': user.email,
            'nome_completo': f'{user.first_name} {user.last_name}'.strip(),
        },
        'organization': {
            'id': str(organization.id),
            'name': organization.name,
            'account_type': organization.account_type,
            'plano_id': organization.plan_id,
        },
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }
