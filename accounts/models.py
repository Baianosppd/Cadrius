import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from billing.models import SubscriptionPlan

class Organization(models.Model):
    # Segurança: UUID evita que IDs sequenciais sejam expostos na URL ou APIs
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, unique=True, null=True, blank=True)
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.RESTRICT, verbose_name="Plano Atual")
    
    # Fundamental para o nosso SSO B2B funcionar (Auto-Provisionamento)
    allowed_domain = models.CharField(
        max_length=255, 
        unique=True, 
        null=True, 
        blank=True, 
        help_text="Ex: machado.adv.br. Usado para vincular utilizadores via Google/Microsoft SSO."
    )
    
    # Controlo de Estado
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Campos extras úteis para futuras integrações (ex: MFA via WhatsApp)
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    # NOTA: Removemos o ForeignKey direto para a Organization daqui.
    # O vínculo agora é feito pela tabela OrganizationMembership abaixo.

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