from django.conf import settings
from django.db import models
from django.db.models import Q


class Notification(models.Model):
    """Notificação do sino, uma linha por destinatário."""

    class Type(models.TextChoices):
        DOCUMENTO = "documento", "Documento"
        PRAZO = "prazo", "Prazo"
        AUTOMACAO = "automacao", "Automação"
        ERRO = "erro", "Erro"
        SUPORTE = "suporte", "Suporte"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    origem = models.CharField(max_length=100, blank=True, default="")
    documento = models.CharField(max_length=255, blank=True, default="")
    acao = models.CharField(max_length=255, blank=True, default="")
    detalhes = models.TextField(blank=True, default="")
    action_label = models.CharField(max_length=100, blank=True, default="")
    link = models.CharField(max_length=255, blank=True, default="")
    # mesmo evento não gera duas notificações para o mesmo utilizador
    dedupe_key = models.CharField(max_length=255, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "read_at"]),
            models.Index(fields=["user", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "dedupe_key"],
                condition=~Q(dedupe_key=""),
                name="notification_unique_user_dedupe_key",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.title}"
