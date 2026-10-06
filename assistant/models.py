"""Conversas com o assistente de IA (CAD-221). Isoladas por escritório E por usuário: ninguém lê a conversa de outra pessoa.

Ações que mudam dados (criar tarefa, contato, minuta, despesa…) nunca rodam direto da IA: viram ``PendingAction`` e só
executam quando a própria pessoa confirma — proteção contra erro do modelo e contra instruções escondidas em documentos.
"""
from django.conf import settings
from django.db import models

from core.utils import EncryptedJSONField, EncryptedTextField


class Conversation(models.Model):
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='assistant_conversations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_conversations')
    title = models.CharField(max_length=120, blank=True, default='')
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
