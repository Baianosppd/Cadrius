"""Portal do cliente (CAD-175): link seguro para o cliente acompanhar os próprios processos e honorários, sem criar conta.

O token só existe no link enviado ao cliente; aqui guardamos apenas o hash (SHA-256). Expira, pode ser revogado a qualquer momento
e cada acesso é contado e auditado. O cliente vê somente o que é dele: processos vinculados ao contato, andamentos em linguagem simples
e (se o escritório quiser) os honorários em aberto com o link de pagamento. Nunca documentos, notas internas ou dados de terceiros."""
from django.conf import settings
from django.db import models


class PortalLink(models.Model):
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='portal_links')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.CASCADE, related_name='portal_links')
    token_hash = models.CharField(max_length=64, unique=True)
    hint = models.CharField(max_length=8)                     # 4 últimos caracteres, para a equipe reconhecer o link
    show_finance = models.BooleanField(default=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_access_at = models.DateTimeField(null=True, blank=True)
    access_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
