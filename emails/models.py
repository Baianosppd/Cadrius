from django.db import models
from django.conf import settings

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
    password = models.CharField(max_length=255) # Lembrete DevSecOps: Encriptar isso no banco no futuro
    
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