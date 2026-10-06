from django.db import models
from django.conf import settings

from core.utils import EncryptedTextField

class MailBox(models.Model):
    """
    Define a caixa de entrada de onde os emails são buscados.
    Agora é apenas um cadastro de credenciais IMAP (um gatilho), 
    sem saber nada sobre regras de negócio ou IA.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE, 
        related_name='mailboxes', 
        verbose_name="Proprietário"
    )
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Nome da Caixa")
    imap_host = models.CharField(max_length=255)
    imap_port = models.IntegerField(default=993)
    username = models.CharField(max_length=255)
    # Cifrada em repouso (Fernet, ver core.utils); transparente ao ler/gravar em Python.
    password = EncryptedTextField()
    
    last_fetch_at = models.DateTimeField(null=True, blank=True, verbose_name="Última Busca")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Caixa de Email"
        verbose_name_plural = "Caixas de Email"

    def __str__(self):
        return self.name


class EmailMessage(models.Model):
    """
    Armazena o email capturado.
    Serve apenas como log/payload inicial de entrada. Não gerencia mais status de IA.
    """
    mailbox = models.ForeignKey(MailBox, on_delete=models.CASCADE, related_name='emails')
    
    message_id = models.CharField(max_length=255, unique=True, help_text="ID único do email (para evitar duplicidade)")
    subject = models.CharField(max_length=500)
    sender = models.EmailField()
    received_at = models.DateTimeField(verbose_name="Recebido em (Timestamp IMAP)")
    body_text = models.TextField(verbose_name="Corpo do Email (Texto Limpo)")
    
    # Flag simples para saber se o orquestrador (workflows) já pegou esse e-mail para processar
    is_dispatched = models.BooleanField(default=False, verbose_name="Despachado para o Orquestrador?")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mensagem de Email"
        verbose_name_plural = "Mensagens de Email"
        indexes = [
            models.Index(fields=['is_dispatched', 'received_at']),
        ]

    def __str__(self):
        return f'{self.subject} - {self.sender}'

class EmailTriage(models.Model):
    """Triagem automática de cada e-mail recebido (CAD-222): categoria, urgência e próxima ação — base do gatilho
    "E-mail recebido" das automações. Regras primeiro (sem custo); IA quando a política do escritório permite."""

    class Category(models.TextChoices):
        INTIMACAO = 'intimacao', 'Intimação / tribunal'
        CLIENTE = 'cliente', 'Mensagem de cliente'
        AGENDA = 'agenda', 'Audiência, reunião ou compromisso'
        FINANCEIRO = 'financeiro', 'Financeiro (boleto, pagamento, nota)'
        COMERCIAL = 'comercial', 'Novo cliente / proposta'
        DOCUMENTO = 'documento', 'Envio de documento'
        MARKETING = 'marketing', 'Propaganda / newsletter'
        OUTRO = 'outro', 'Outro'

    class Urgency(models.TextChoices):
        ALTA = 'alta', 'Alta'
        MEDIA = 'media', 'Média'
        BAIXA = 'baixa', 'Baixa'

    email = models.OneToOneField(EmailMessage, on_delete=models.CASCADE, related_name='triage')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='email_triages')
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OUTRO, db_index=True)
    urgency = models.CharField(max_length=6, choices=Urgency.choices, default=Urgency.MEDIA)
    summary = EncryptedTextField(blank=True, default='')
    suggested_action = models.CharField(max_length=200, blank=True, default='')
    due_date = models.DateField(null=True, blank=True)
    contact = models.ForeignKey('contacts.Contact', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    method = models.CharField(max_length=6, default='regras')          # regras | ia
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
