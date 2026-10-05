"""Suporte ao usuário com a equipe Cadrius (CAD-171). Mensagens cifradas. A equipe NÃO vê dados do escritório por padrão:
o cliente concede acesso assistido temporário (só leitura, com prazo) quando o chamado exige."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.utils import EncryptedTextField


class Ticket(models.Model):
    class Category(models.TextChoices):
        QUESTION = 'duvida', 'Dúvida'
        PROBLEM = 'problema', 'Problema / erro'
        BILLING = 'financeiro', 'Financeiro / assinatura'
        INTEGRATION = 'integracao', 'Integração'
        SUGGESTION = 'sugestao', 'Sugestão'
        OTHER = 'outro', 'Outro'

    class Priority(models.TextChoices):
        LOW = 'baixa', 'Baixa'
        NORMAL = 'normal', 'Normal'
        HIGH = 'alta', 'Alta'
        URGENT = 'urgente', 'Urgente'

    class Status(models.TextChoices):
        OPEN = 'aberto', 'Aberto'
        IN_PROGRESS = 'em_andamento', 'Em andamento'
        WAITING_CLIENT = 'aguardando_cliente', 'Aguardando você'
        RESOLVED = 'resolvido', 'Resolvido'
        CLOSED = 'fechado', 'Fechado'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='support_tickets')
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='support_tickets')
    subject = EncryptedTextField()
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.QUESTION)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    page_url = models.CharField(max_length=300, blank=True, default='')       # tela de onde o chamado foi aberto
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']

    def active_grant(self):
        return self.access_grants.filter(revoked_at__isnull=True, expires_at__gt=timezone.now()).order_by('-expires_at').first()


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    from_staff = models.BooleanField(default=False)
    internal = models.BooleanField(default=False)          # nota interna da equipe: o cliente nunca vê
    body = EncryptedTextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class SupportAccessGrant(models.Model):
    """Autorização do cliente para a equipe olhar os dados do escritório neste chamado (só leitura, com validade)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='access_grants')
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
