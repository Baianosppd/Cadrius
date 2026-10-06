"""Conversas com o assistente de IA (CAD-221). Isoladas por escritório E por usuário: ninguém lê a conversa de outra pessoa.

Ações que mudam dados (criar tarefa, contato, minuta, despesa…) nunca rodam direto da IA: viram ``PendingAction`` e só
executam quando a própria pessoa confirma — proteção contra erro do modelo e contra instruções escondidas em documentos.
"""
from django.conf import settings
from django.db import models

from core.utils import EncryptedJSONField, EncryptedTextField


class AssistantSettings(models.Model):
    """Escolhas do escritório para o assistente (CAD-222). Quem decide é dono/admin."""

    organization = models.OneToOneField('accounts.Organization', on_delete=models.CASCADE, related_name='assistant_settings')
    case_strategy = models.BooleanField(default=False, help_text='Modo "estratégia de caso" disponível para a equipe.')
    mcp_enabled = models.BooleanField(default=False, help_text='Permite ligar o conector do Cadrius no Claude/ChatGPT.')
    use_memory = models.BooleanField(default=True, help_text='O assistente consulta a memória do escritório em cada pergunta.')
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def of(cls, org) -> 'AssistantSettings':
        obj, _ = cls.objects.get_or_create(organization=org)
        return obj


class Conversation(models.Model):
    class Mode(models.TextChoices):
        GERAL = 'geral', 'Assistente'
        CASO = 'caso', 'Estratégia de caso'
        MCP = 'mcp', 'Pedidos pelo conector (Claude/ChatGPT)'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='assistant_conversations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_conversations')
    title = models.CharField(max_length=120, blank=True, default='')
    mode = models.CharField(max_length=6, choices=Mode.choices, default=Mode.GERAL)
    case = models.ForeignKey('research.MonitoredCase', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    contact = models.ForeignKey('contacts.Contact', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['organization', 'user', '-updated_at'])]


class Message(models.Model):
    class Role(models.TextChoices):
        USER = 'user', 'Usuário'
        ASSISTANT = 'assistant', 'Assistente'
        NOTE = 'note', 'Registro do sistema'

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=Role.choices)
    content = EncryptedTextField(blank=True, default='')           # pode conter dado de cliente: cifrado em repouso
    provider = models.CharField(max_length=16, blank=True, default='')
    tools = models.JSONField(default=list, blank=True)            # só os NOMES das ferramentas usadas (sem dados)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class PendingAction(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Aguardando confirmação'
        DONE = 'done', 'Executada'
        CANCELED = 'canceled', 'Cancelada'
        FAILED = 'failed', 'Falhou'

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='actions')
    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.SET_NULL, related_name='actions')
    tool = models.CharField(max_length=40)
    arguments = EncryptedJSONField(default=dict, blank=True)
    summary = EncryptedTextField(blank=True, default='')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    result = EncryptedJSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']


class PersonalToken(models.Model):
    """Token pessoal do conector MCP (CAD-222): liga o Cadrius ao Claude (Pro/Max/Team), ChatGPT ou Claude Code da própria
    pessoa. Guardamos só o hash; o token aparece uma vez. Escopo "leitura" consulta; "pedidos" também prepara ações, que
    continuam exigindo confirmação dentro do Cadrius."""

    class Scope(models.TextChoices):
        READ = 'leitura', 'Só consultar'
        REQUESTS = 'pedidos', 'Consultar e preparar pedidos (confirmados no Cadrius)'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='personal_tokens')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='personal_tokens')
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=12)
    token_hash = models.CharField(max_length=64, unique=True)
    scope = models.CharField(max_length=8, choices=Scope.choices, default=Scope.READ)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    uses = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']


class OrgAIKey(models.Model):
    """Conta de IA do próprio escritório (CAD-222, "traga sua chave"): o assistente usa a chave do escritório em vez da
    do Cadrius e não consome créditos. Cifrada em repouso; nunca volta para a tela (só os 4 últimos caracteres)."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='ai_keys')
    provider = models.CharField(max_length=16)
    api_key = EncryptedTextField()
    base_url = models.CharField(max_length=255, blank=True, default='')      # só para Ollama/compatível do escritório
    model = models.CharField(max_length=80, blank=True, default='')
    paid_account = models.BooleanField(default=True, help_text='Conta paga (provedor não treina com os dados).')
    last4 = models.CharField(max_length=4, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'provider'], name='uniq_ai_key_per_org_provider')]
