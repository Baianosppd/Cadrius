import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from billing.models import SubscriptionPlan

class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Identificação da Empresa
    name = models.CharField(max_length=255, verbose_name="Nome Interno")
    nome_fantasia = models.CharField(max_length=255, null=True, blank=True)
    razao_social = models.CharField(max_length=255, null=True, blank=True)
    cnpj = models.CharField(max_length=18, unique=True, null=True, blank=True)
    
    # Natureza Jurídica / Fiscal
    company_type = models.CharField(max_length=100, null=True, blank=True, verbose_name="Tipo de Sociedade")
    tax_regime = models.CharField(max_length=100, null=True, blank=True, verbose_name="Regime Tributário")
    
    # Endereço
    cep = models.CharField(max_length=9, null=True, blank=True)
    street = models.CharField(max_length=255, null=True, blank=True, verbose_name="Logradouro")
    number = models.CharField(max_length=20, null=True, blank=True, verbose_name="Número")
    neighborhood = models.CharField(max_length=100, null=True, blank=True, verbose_name="Bairro")
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="Cidade")
    state_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="Estado (UF)")
    
    # Contatos
    main_phone = models.CharField(max_length=20, null=True, blank=True, verbose_name="Telefone Principal")
    corporate_phone = models.CharField(max_length=20, null=True, blank=True, verbose_name="Telefone Corporativo")

    # SSO e Plano
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.RESTRICT, verbose_name="Plano Atual")
    allowed_domain = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.nome_fantasia or self.razao_social or self.name


class CustomUser(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Novos campos do Advogado / Indivíduo
    cpf = models.CharField(max_length=14, unique=True, null=True, blank=True)
    oab_number = models.CharField(max_length=20, null=True, blank=True, verbose_name="Número da OAB")
    oab_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="Estado da OAB (UF)")
    practice_area = models.CharField(max_length=100, null=True, blank=True, verbose_name="Área de Atuação Principal")

    profile_picture = models.ImageField(
        upload_to='users/avatars/', 
        null=True, 
        blank=True, 
        verbose_name="Foto de Perfil"
    )

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
    
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Garante que a mesma pessoa não é adicionada duas vezes no mesmo escritório
        unique_together = ('user', 'organization')

    def __str__(self):
        return f"{self.user.email} - {self.organization.name} ({self.role})"