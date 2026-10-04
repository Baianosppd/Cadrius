import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from billing.models import SubscriptionPlan
from core.pii import PIIIndexMixin
from core.utils import EncryptedTextField

class Organization(PIIIndexMixin, models.Model):
    # Dados pessoais/de contato cifrados em repouso (CAD-152); CNPJ tem índice cego para unicidade e busca exata.
    BLIND_INDEXES = {'cnpj': ('cnpj_bidx', 'org.cnpj', 'digits')}

    ACCOUNT_TYPE_CHOICES = (
        ('PESSOA_FISICA', 'Pessoa Física'),
        ('EMPRESA', 'Empresa'),
    )
    COMPANY_SIZE_CHOICES = (
        ('MEI', 'Microempreendedor Individual'),
        ('ME', 'Microempresa'),
        ('EPP', 'Empresa de Pequeno Porte'),
        ('GRANDE_PORTE', 'Grande Porte'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPE_CHOICES,
        default='EMPRESA',
        verbose_name="Tipo de Conta",
    )
    
    # Identificação da Empresa
    name = models.CharField(max_length=255, verbose_name="Nome Interno")
    nome_fantasia = models.CharField(max_length=255, null=True, blank=True)
    razao_social = models.CharField(max_length=255, null=True, blank=True)
    cnpj = EncryptedTextField(null=True, blank=True)
    cnpj_bidx = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    
    # Natureza Jurídica / Fiscal
    company_type = models.CharField(max_length=100, null=True, blank=True, verbose_name="Tipo de Sociedade")
    tax_regime = models.CharField(max_length=100, null=True, blank=True, verbose_name="Regime Tributário")
    company_size = models.CharField(
        max_length=20,
        choices=COMPANY_SIZE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Porte da Empresa",
    )
    
    # Endereço
    cep = EncryptedTextField(null=True, blank=True)
    street = EncryptedTextField(null=True, blank=True, verbose_name="Logradouro")
    number = EncryptedTextField(null=True, blank=True, verbose_name="Número")
    neighborhood = EncryptedTextField(null=True, blank=True, verbose_name="Bairro")
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="Cidade")
    state_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="Estado (UF)")
    
    # Contatos
    main_phone = EncryptedTextField(null=True, blank=True, verbose_name="Telefone Principal")
    corporate_phone = EncryptedTextField(null=True, blank=True, verbose_name="Telefone Corporativo")
    corporate_email = EncryptedTextField(null=True, blank=True, verbose_name="E-mail Corporativo")

    # SSO e Plano
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.RESTRICT, verbose_name="Plano Atual")
    next_billing_date = models.DateField(null=True, blank=True, verbose_name="Próxima Cobrança")

    # Assinatura (CAD-119). O plano em ``plan`` é o plano ESCOLHIDO; o que vale na prática depende do estado
    # (ver billing/entitlements.py): em trial/sem pagamento os limites são os do trial, não os do plano pago.
    class SubscriptionStatus(models.TextChoices):
        TRIALING = 'trialing', 'Em teste'
        ACTIVE = 'active', 'Ativa'
        PAST_DUE = 'past_due', 'Pagamento pendente'
        RESTRICTED = 'restricted', 'Restrita'
        SUSPENDED = 'suspended', 'Suspensa'
        CANCELED = 'canceled', 'Cancelada'

    # default ACTIVE: escritórios legados/semeados continuam com os limites do plano; o cadastro novo define TRIALING.
    subscription_status = models.CharField(max_length=12, choices=SubscriptionStatus.choices, default='active')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    past_due_since = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=64, blank=True, default='')
    stripe_subscription_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    allowed_domain = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nome_fantasia or self.razao_social or self.name


class CustomUser(PIIIndexMixin, AbstractUser):
    # Dados pessoais cifrados em repouso (CAD-152). E-mail/username ficam em claro: são o identificador de login.
    # Busca: CPF por índice cego (exato, único); nome por índice de tokens (parcial). Ver core/pii.py.
    BLIND_INDEXES = {'cpf': ('cpf_bidx', 'user.cpf', 'digits')}
    TOKEN_INDEXES = {('first_name', 'last_name'): ('name_idx', 'user.name')}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = EncryptedTextField('first name', blank=True)
    last_name = EncryptedTextField('last name', blank=True)
    name_idx = models.TextField(blank=True, default='', editable=False)
    phone = EncryptedTextField(blank=True, null=True)
    
    # Novos campos do Advogado / Indivíduo
    cpf = EncryptedTextField(null=True, blank=True)
    cpf_bidx = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    oab_number = EncryptedTextField(null=True, blank=True, verbose_name="Número da OAB")
    oab_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="Estado da OAB (UF)")
    practice_area = models.CharField(max_length=100, null=True, blank=True, verbose_name="Área de Atuação Principal")

    profile_picture = models.ImageField(
        upload_to='users/avatars/', 
        null=True, 
        blank=True, 
        verbose_name="Foto de Perfil"
    )

    @property
    def organization(self):
        """
        Escritório ativo associado ao utilizador (primeira membership ativa).
        Alinha ``request.user.organization`` com o modelo multi-tenant real.
        """
        membership = (
            self.memberships.filter(is_active=True)
            .select_related("organization")
            .first()
        )
        return membership.organization if membership else None

    def __str__(self):
        return self.email or self.username


class OrganizationMembership(models.Model):
    """
    Permite que um utilizador pertença a várias organizações com permissões diferentes.
    Ex: O Jullio pode ser 'OWNER' no Cadrius e 'MEMBER' no escritório de um parceiro.
    """
    ROLE_CHOICES = (
        ('OWNER', 'Dono do Escritório'),
        ('ADMIN', 'Administrador'),
        ('MEMBER', 'Advogado/Membro'),
        ('VIEWER', 'Apenas Leitura'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='members')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='MEMBER')
    job_title = models.CharField(max_length=100, blank=True, default='', verbose_name="Cargo")
    # null = sem cota individual (consome só do total do plano)
    credit_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Cota mensal de créditos",
    )
    
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Garante que a mesma pessoa não é adicionada duas vezes no mesmo escritório
        unique_together = ('user', 'organization')

    def __str__(self):
        return f"{self.user.email} - {self.organization.name} ({self.role})"


class UserMessageSendCount(models.Model):
    """Métricas de uso por utilizador (dashboard e limites)."""

    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='message_send_count',
        verbose_name='Utilizador',
    )
    whatsapp_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Envios WhatsApp',
    )
    email_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Envios e-mail',
    )
    automations_run_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Automações executadas',
    )
    document_analysis_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Análises de documento',
    )

    class Meta:
        verbose_name = 'Contagem de uso do utilizador'
        verbose_name_plural = 'Contagens de uso dos utilizadores'

    def __str__(self):
        return (
            f"{self.user.email}: WA {self.whatsapp_count}, e-mail {self.email_count}, "
            f"auto {self.automations_run_count}, docs {self.document_analysis_count}"
        )

    @property
    def messages_sent_total(self) -> int:
        return self.whatsapp_count + self.email_count


class SocialIdentity(models.Model):
    """Vínculo estável entre um usuário e a identidade no provedor de SSO (CAD-105).
    O login seguinte usa (provedor, subject) — não depende do e-mail, que pode mudar ou ser falsificado."""

    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='social_identities')
    provider = models.CharField(max_length=20)
    subject = models.CharField(max_length=255)
    email_at_link = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['provider', 'subject'], name='uniq_social_identity')]

    def __str__(self):
        return f'{self.provider}:{self.user_id}'
