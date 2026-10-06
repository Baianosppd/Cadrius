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
        CUSTOMIZATION = 'parametrizacao', 'Pedido de parametrização'      # CAD-223
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


class CustomizationRequest(models.Model):
    """Pedido de parametrização (CAD-223): o escritório descreve algo específico que quer configurado (uma automação, um relatório,
    um modelo de documento, uma integração, acessos...). A equipe Cadrius analisa, propõe (prazo e, se houver, custo) e só executa
    depois do "aprovo" do dono/admin. Ligado a um chamado para a conversa seguir no mesmo lugar."""

    class Area(models.TextChoices):
        AUTOMATION = 'automacao', 'Automação / gatilho'
        INTEGRATION = 'integracao', 'Integração com outro sistema'
        REPORT = 'relatorio', 'Relatório ou painel'
        TEMPLATE = 'modelo', 'Modelo de documento / minuta'
        ACCESS = 'acessos', 'Grupos de acesso da equipe'
        FINANCE = 'financeiro', 'Financeiro / cobrança'
        FISCAL = 'fiscal', 'Fiscal / nota fiscal'
        MARKETING = 'marketing', 'Marketing / captação'
        IMPORT = 'importacao', 'Importação de dados'
        COURTS = 'tribunais', 'Tribunais / prazos'
        OTHER = 'outro', 'Outro'

    class Stage(models.TextChoices):
        RECEIVED = 'recebido', 'Recebido'
        ANALYSIS = 'em_analise', 'Em análise'
        PROPOSAL = 'proposta', 'Proposta enviada (aguardando você)'
        APPROVED = 'aprovado', 'Aprovado pelo escritório'
        IN_PROGRESS = 'em_execucao', 'Em execução'
        DELIVERED = 'entregue', 'Entregue'
        DECLINED = 'recusado', 'Não será feito'
        CANCELED = 'cancelado', 'Cancelado pelo escritório'

    ticket = models.OneToOneField(Ticket, on_delete=models.CASCADE, related_name='customization')
    area = models.CharField(max_length=12, choices=Area.choices)
    objective = EncryptedTextField()                         # o que precisa e por quê
    example = EncryptedTextField(blank=True, default='')     # exemplo concreto / como é feito hoje
    frequency = models.CharField(max_length=40, blank=True, default='')   # ex.: "toda publicação nova"
    users_affected = models.PositiveSmallIntegerField(default=1)
    wanted_by = models.DateField(null=True, blank=True)
    stage = models.CharField(max_length=12, choices=Stage.choices, default=Stage.RECEIVED, db_index=True)
    proposal = EncryptedTextField(blank=True, default='')    # o que será feito, prazo e custo (se houver)
    estimate_days = models.PositiveSmallIntegerField(null=True, blank=True)
    price_cents = models.PositiveIntegerField(null=True, blank=True)       # null = sem custo (incluído no plano)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
