from django.conf import settings
from django.db import models
from django.utils import timezone

from core.pii import PIIIndexMixin
from core.storage import encrypted_storage
from core.utils import EncryptedJSONField, EncryptedTextField


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
    # Conteúdo cifrado em repouso (core/storage.py); baixar é pelo endpoint /documentos/<id>/download/ (decifra na saída).
    arquivo = models.FileField(upload_to="documents/%Y/%m/", max_length=500, storage=encrypted_storage)
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


class ClientDocument(PIIIndexMixin, models.Model):
    """
    Vínculo opcional documento ↔ nome do cliente (ainda sem model Client).
    """

    # Nome do cliente do escritório = dado pessoal de terceiro: cifrado; busca parcial por índice de tokens (core/pii.py).
    TOKEN_INDEXES = {('nome_cliente',): ('nome_cliente_idx', 'client.name')}

    nome_cliente = EncryptedTextField()
    nome_cliente_idx = models.TextField(blank=True, default='', editable=False)
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

    def __str__(self):
        return f"{self.nome_cliente} → {self.documento_id}"


class DocumentExtraction(models.Model):
    """Resultado da leitura automática de um documento (CAD-163). Nada vira "fato" no sistema sem a confirmação de uma pessoa."""

    class Status(models.TextChoices):
        PENDING = "pending", "Na fila"
        PROCESSING = "processing", "Processando"
        REVIEW = "review", "Aguardando revisão"
        CONFIRMED = "confirmed", "Confirmado"
        FAILED = "failed", "Falhou"
        SKIPPED = "skipped", "Não processado"

    document = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="extraction")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    stage = models.CharField(max_length=20, blank=True, default="")        # onde parou: scan | text | ocr | ai | review
    detected_kind = models.CharField(max_length=10, blank=True, default="")  # pdf | docx | txt | png | jpeg
    text_chars = models.PositiveIntegerField(default=0)
    ocr_used = models.BooleanField(default=False)
    provider = models.CharField(max_length=10, blank=True, default="")
    confidence = models.PositiveSmallIntegerField(null=True, blank=True)
    # dados extraídos (podem conter nomes de partes): cifrados em repouso
    fields = EncryptedJSONField(default=dict, blank=True)
    message = models.CharField(max_length=255, blank=True, default="")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
