"""Minutas (CAD-173): rascunhos de peças e comunicações gerados sobre um documento ou uma publicação, a partir de um modelo
(do Cadrius ou do escritório). Sempre rascunho: quem revisa e assina é o advogado. Cada minuta guarda os trechos da fonte que usou."""
from django.conf import settings
from django.db import models

from core.utils import EncryptedJSONField, EncryptedTextField


class DraftTemplate(models.Model):
    """Modelo do escritório (os do Cadrius ficam em ``minutas.builtin``). Corpo com variáveis ``{{processo.cnj}}``."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='draft_templates')
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=40, default='outro')
    body = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']


class Draft(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'rascunho', 'Rascunho'
        REVIEWED = 'revisada', 'Revisada'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='drafts')
    template_key = models.CharField(max_length=60)                 # 'builtin:<chave>' ou 'org:<id>'
    title = models.CharField(max_length=200)
    source_type = models.CharField(max_length=12, blank=True, default='')   # documento | publicacao | ''
    source_id = models.PositiveIntegerField(null=True, blank=True)
    content = EncryptedTextField(blank=True, default='')
    citations = EncryptedJSONField(default=list, blank=True)        # [{trecho, origem, conferido}]
    pending = models.PositiveSmallIntegerField(default=0)           # quantos [COMPLETAR] ainda há no texto
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    ai_provider = models.CharField(max_length=16, blank=True, default='')   # vazio = só modelo (sem IA)
    notice = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
