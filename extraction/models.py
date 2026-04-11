# extraction/models.py
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class ExtractionProfile(models.Model):
    """
    Define um perfil de extração com um System Prompt customizado, 
    um Schema Pydantic alvo e a escolha do provedor de IA.
    """
    
    PROVIDER_CHOICES = (
        ('OPENAI', 'OpenAI (GPT-3.5/GPT-4)'),
        ('GEMINI', 'Google Gemini (1.5 Flash)'),
        ('GROQ', 'Llama 3 (via Groq)'),
    )

    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='extraction_profiles', 
        verbose_name="Proprietário"
    )
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Nome do Perfil")
    
    # NOVO: O utilizador ou admin escolhe qual IA vai ler o e-mail/webhook
    ai_provider = models.CharField(
        max_length=20, 
        choices=PROVIDER_CHOICES, 
        default='OPENAI', 
        verbose_name="Motor de IA"
    )
    
    system_prompt_template = models.TextField(
        verbose_name="System Prompt Template",
        help_text="Instrução detalhada para a IA. Use {data_atual} para a data de hoje."
    )
    
    pydantic_schema_name = models.CharField(
        max_length=100,
        verbose_name="Nome do Schema Pydantic",
        help_text="Nome da classe do schema em extraction.schemas (Ex: ProcessoJuridicoSchema)."
    )

    class Meta:
        verbose_name = "Perfil de Extração (Prompt)"
        verbose_name_plural = "Perfis de Extração (Prompts)"

    def __str__(self):
        return f"{self.name} ({self.get_ai_provider_display()})"