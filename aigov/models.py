from django.db import models
from django.utils import timezone

DEFAULT_PROVIDERS = ['OPENAI', 'GEMINI', 'GROQ']


class AIGovernancePolicy(models.Model):
    """
    Política de IA por escritório. Defesa em profundidade para IA autônoma em contexto jurídico:
    desligamento (kill switch), restrição de provedores, limites, aprovação humana de workflows
    gerados por IA (RNE-016) e confirmação humana de ações disparadas por conteúdo extraído por IA.
    """

    class Autonomy(models.TextChoices):
        OFF = 'off', 'Desligada — nenhuma chamada de IA'
        SUGGEST = 'suggest', 'Somente sugestões — IA gera rascunhos; nada executa sem confirmação humana'
        SUPERVISED = 'supervised', 'Supervisionada (padrão) — rascunhos exigem aprovação; ações externas de origem IA exigem confirmação'
        AUTONOMOUS_LIMITED = 'autonomous_limited', 'Autonomia limitada — workflows aprovados executam sozinhos (aprovação de rascunhos continua obrigatória)'

    organization = models.OneToOneField('accounts.Organization', on_delete=models.CASCADE, related_name='ai_policy')
    ai_enabled = models.BooleanField(default=True, help_text='Kill switch do escritório.')
    autonomy_level = models.CharField(max_length=24, choices=Autonomy.choices, default=Autonomy.SUPERVISED)
    allowed_providers = models.JSONField(default=list, help_text='Provedores permitidos: OPENAI, GEMINI, GROQ.')
    daily_ai_request_limit = models.PositiveIntegerField(default=500)
    max_actions_per_ai_workflow = models.PositiveSmallIntegerField(default=5)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=64, blank=True)

    def save(self, *args, **kwargs):
        if not self.allowed_providers:
            self.allowed_providers = list(DEFAULT_PROVIDERS)
        super().save(*args, **kwargs)

    def requires_execution_review(self) -> bool:
        """Ações de origem IA exigem confirmação humana antes de sair do sistema?"""
        return self.autonomy_level in (self.Autonomy.SUGGEST, self.Autonomy.SUPERVISED)


class GlobalAISwitch(models.Model):
    """Kill switch da PLATAFORMA (equipe de segurança): corta toda a IA sem precisar de deploy."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    ai_enabled = models.BooleanField(default=True)
    reason = models.CharField(max_length=255, blank=True)
    changed_by = models.CharField(max_length=64, blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    @classmethod
    def get(cls) -> 'GlobalAISwitch':
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class AIActionLog(models.Model):
    """
    Registro de CADA uso de IA: quem, quando, provedor, categorias de dados e resultado —
    **sem o conteúdo**. Alimenta o inventário de suboperadores e a tela de governança.
    """

    class Kind(models.TextChoices):
        EXTRACTION = 'extraction', 'Extração de dados'
        WORKFLOW_GENERATION = 'workflow_generation', 'Geração de workflow'

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    organization_id = models.UUIDField(null=True, db_index=True)
    user_ref = models.CharField(max_length=64, blank=True)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    provider = models.CharField(max_length=16)
    data_categories = models.JSONField(default=list)
    input_chars = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    blocked = models.BooleanField(default=False)
    block_reason = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization_id', 'created_at'])]


