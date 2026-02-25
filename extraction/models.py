# julliodutra/cadrius/cadrius-d2664e7d9d3cdaaeb4729d29c9fafb13438707c0/extraction/models.py
from django.db import models
from django.contrib.auth import get_user_model




User = get_user_model()
# NOVO MODELO: Para definir dinamicamente o prompt e a função da IA
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
    
    # O prompt base que a IA usará. O corpo do email será anexado.
    system_prompt_template = models.TextField(
        verbose_name="System Prompt Template",
        help_text="Instrução detalhada para a IA. Use {data_atual} para a data de hoje."
    )
    
    # Qual schema Pydantic esse perfil deve usar para validação (Ex: ProcessoJuridicoSchema)
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

# Create your models here.