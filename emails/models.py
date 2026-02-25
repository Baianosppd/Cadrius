from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings  # <--- IMPORTAÇÃO NECESSÁRIA ADICIONADA

User = get_user_model()

# Status de processamento do email
class EmailStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pendente de Processamento'
    PROCESSING = 'PROCESSING', 'Em Processamento'
    EXTRACTED = 'EXTRACTED', 'Dados Extraídos com Sucesso'
    REQUIRES_REVIEW = 'REVIEW', 'Requer Revisão Humana (IA Falhou)'
    INTEGRATED = 'INTEGRATED', 'Integrado (Trello/Telegram OK)'
    FAILED = 'FAILED', 'Falha Crítica'


class MailBox(models.Model):
    """
    Define a caixa de entrada de onde os emails são buscados.
    Responsabilidade: Jullio (Modelagem) e Thales (Uso no Worker IMAP).
    """
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, # <--- Recomendado usar settings aqui também
        on_delete=models.CASCADE, 
        related_name='mailboxes', 
        verbose_name="Proprietário"
    )
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Nome da Caixa")
    # Para simplificar, armazenaremos as credenciais diretamente aqui, 
    # mas em produção deve-se usar um Secret Manager.
    imap_host = models.CharField(max_length=255)
    imap_port = models.IntegerField(default=993)
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255) # Campo para a senha
    
    # NOVO CAMPO (Correção Circular: Usando string de referência 'integrations.IntegrationConfig')
    integration_config = models.ForeignKey(
        'integrations.IntegrationConfig', # Usando string reference
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='mailboxes',
        verbose_name="Configuração de Integração Externa"
    )
    
    # NOVO CAMPO (Correção Circular: Usando string de referência 'extraction.ExtractionProfile')
    extraction_profile = models.ForeignKey(
        'extraction.ExtractionProfile', # Usando string reference
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='mailboxes',
        verbose_name="Perfil de Extração de IA"
    )
    
    last_fetch_at = models.DateTimeField(null=True, blank=True, verbose_name="Última Busca")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Caixa de Email"
        verbose_name_plural = "Caixas de Email"

    def __str__(self):
        return self.name


class EmailMessage(models.Model):
    """
    Armazena o email capturado e seu status de processamento.
    Serve como a principal tabela de trabalho do sistema.
    """
    mailbox = models.ForeignKey(MailBox, on_delete=models.PROTECT, related_name='emails')
    
    # Metadados do Email (Preenchido por Thales no fetch_emails)
    message_id = models.CharField(max_length=255, unique=True, help_text="ID único do email (para idempotência)")
    subject = models.CharField(max_length=500)
    sender = models.EmailField()
    received_at = models.DateTimeField(verbose_name="Recebido em (Timestamp IMAP)")
    body_text = models.TextField(verbose_name="Corpo do Email (Texto Limpo)")
    
    # Status e Logs
    status = models.CharField(
        max_length=20,
        choices=EmailStatus.choices,
        default=EmailStatus.PENDING
    )
    
    # Dados Extraídos (Preenchido por Juliano após o Wrapper de IA)
    # JSONField é ideal para armazenar a saída do ChatGPT validada pelo Pydantic.
    extracted_data = models.JSONField(
        null=True, blank=True, 
        help_text="Dados chave extraídos pela IA (JSON validado)"
    )
    
    # Controles de Processamento
    processing_attempts = models.IntegerField(default=0)
    last_processed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mensagem de Email"
        verbose_name_plural = "Mensagens de Email"
        # Jullio: Adicionar índice no campo 'status' para consultas rápidas
        indexes = [
            models.Index(fields=['status', 'received_at']),
        ]

    def __str__(self):
        return f'[{self.status}] {self.subject} - {self.sender}'

    # Método que Thales pode chamar no pipeline para re-enfileirar
    def re_enqueue_for_processing(self):
        """
        Marca o email para ser re-processado, útil após falhas ou revisão.
        """
        self.status = EmailStatus.PENDING
        self.processing_attempts += 1
        self.save()


class AutomationRule(models.Model):
    """
    Define a lógica de negócio de um cliente: SE (condição) ENTAO (perfil IA).
    Permite que o sistema reaja a diferentes tipos de e-mail na mesma MailBox.
    """
    # Multi-Tenancy: A regra é do usuário
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,  # <--- CORREÇÃO AQUI: Aponta para o modelo configurado no settings
        on_delete=models.CASCADE, 
        related_name='automation_rules', 
        verbose_name="Proprietário"
    )
    
    # A regra se aplica a uma Caixa de E-mail
    mailbox = models.ForeignKey(
        'MailBox', # Linka à MailBox onde a regra se aplica
        on_delete=models.CASCADE, 
        related_name='rules',
        verbose_name="Caixa de E-mail Alvo"
    )
    
    name = models.CharField(max_length=100, verbose_name="Nome da Regra")
    priority = models.IntegerField(default=10, help_text="Prioridade de execução. Menor número é executado primeiro.")
    is_active = models.BooleanField(default=True)

    # CONDIÇÃO: Filtro básico de e-mail (SE)
    subject_contains = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="Texto que o Assunto DEVE conter (deixe vazio para ignorar)."
    )
    sender_contains = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="Texto que o Remetente DEVE conter (deixe vazio para ignorar)."
    )
    
    # AÇÃO: O que fazer se a condição for atendida (ENTÃO)
    # O perfil de extração define o Schema Pydantic e o Prompt
    extraction_profile = models.ForeignKey(
        'extraction.ExtractionProfile', 
        on_delete=models.SET_NULL, 
        null=True, 
        verbose_name="Perfil de Extração (IA) a ser usado"
    )
    
    # Futuramente: Ações de integração adicionais podem ser definidas aqui
    action_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Configurações para ações pós-extração (ex: Trello, Telegram)."
    )
    
    class Meta:
        verbose_name = "Regra de Automação"
        verbose_name_plural = "Regras de Automação"
        ordering = ['priority', 'name']
        # Garante que não haja duas regras com o mesmo nome na mesma MailBox
        unique_together = ('mailbox', 'name') 

    def __str__(self):
        return f'{self.name} ({self.mailbox.name})'