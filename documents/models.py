from django.conf import settings
from django.db import models
from django.utils import timezone


class Document(models.Model):
    """
    Documento do escritório: ficheiro em MEDIA_ROOT, metadados na BD.
    Cliente fica fora deste model (integração opcional futura).
    """

    class Tipo(models.TextChoices):
        CONTRATO = "contrato", "Contrato"
        PETICAO = "peticao", "Petição"
        PROCURACAO = "procuracao", "Procuração"
        OUTRO = "outro", "Outro"

    class Status(models.TextChoices):
        PROCESSANDO = "processando", "Processando"
        PRONTO = "pronto", "Pronto"
        AGUARDANDO_ASSINATURA = "aguardando_assinatura", "Aguardando assinatura"
        ASSINADO = "assinado", "Assinado"

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    nome = models.CharField(max_length=255)
    tipo = models.CharField(
        max_length=50,
        choices=Tipo.choices,
        default=Tipo.OUTRO,
    )
    status = models.CharField(
        max_length=50,
        choices=Status.choices,
        default=Status.PROCESSANDO,
    )
    data = models.DateTimeField(default=timezone.now)
    arquivo = models.FileField(upload_to="documents/%Y/%m/", max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Documento"
        verbose_name_plural = "Documentos"
        indexes = [
            models.Index(fields=["organization", "nome"]),
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self):
        return self.nome


class ClientDocument(models.Model):
    """
    Vínculo opcional documento ↔ nome do cliente (ainda sem model Client).
    """

    nome_cliente = models.CharField(max_length=255)
    documento = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="client_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Documento do cliente"
        verbose_name_plural = "Documentos do cliente"
        indexes = [
            models.Index(fields=["nome_cliente"]),
        ]

    def __str__(self):
        return f"{self.nome_cliente} → {self.documento_id}"
