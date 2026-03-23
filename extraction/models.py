# julliodutra/cadrius/cadrius-d2664e7d9d3cdaaeb4729d29c9fafb13438707c0/extraction/models.py
from django.db import models
from django.contrib.auth import get_user_model




User = get_user_model()

class ExtractionProfile(models.Model):
    """
    Define um perfil de extração com um System Prompt customizado e 
    um Schema Pydantic alvo, permitindo novas funcionalidades.
    """
    
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='extraction_profiles', 
        verbose_name="Proprietário"
    )
    
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Nome do Perfil")
    
    
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
        return self.name

