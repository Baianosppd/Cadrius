"""Conector declarativo de ERP jurídico (CAD-167). Credenciais cifradas e write-only; toda chamada fica registrada (sem segredos)."""
from django.conf import settings
from django.db import models

from core.utils import EncryptedJSONField


class ErpConnector(models.Model):
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='erp_connectors')
    name = models.CharField(max_length=100)
    preset = models.CharField(max_length=20)
    base_url = models.URLField(max_length=300)
    credentials = EncryptedJSONField(default=dict)
    operations = models.JSONField(default=dict, blank=True)   # sobrescreve/estende as operações do modelo
    live_enabled = models.BooleanField(default=False)          # enquanto False, só simulação (dry-run)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'name'], name='uniq_erp_name_per_org')]


class ErpCallLog(models.Model):
    connector = models.ForeignKey(ErpConnector, on_delete=models.CASCADE, related_name='calls')
    operation = models.CharField(max_length=60)
    dry_run = models.BooleanField(default=True)
    ok = models.BooleanField(default=False)
    status_code = models.IntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True, default='')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
