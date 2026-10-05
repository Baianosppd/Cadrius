"""Motor Cadrius (CAD-165): memória do escritório, feedback, regras aprendidas e matriz de autonomia.

Tudo é isolado por escritório (``organization``). O conteúdo (textos, embeddings, antes/depois) é cifrado em repouso.
Nada aqui treina modelo de terceiros: aprender = lembrar decisões aprovadas, propor regras que o advogado aprova e medir a taxa de acerto.
"""
from django.conf import settings
from django.db import models

from core.utils import EncryptedJSONField, EncryptedTextField


class MemoryItem(models.Model):
    class Kind(models.TextChoices):
        EXTRACTION_EXAMPLE = 'extraction_example', 'Exemplo de leitura aprovada'
        TEMPLATE = 'template', 'Modelo de peça'
        NOTE = 'note', 'Anotação do escritório'
        DECISION = 'decision', 'Decisão/entendimento'
        DRAFT_EXAMPLE = 'draft_example', 'Minuta revisada'
        MARKETING_EXAMPLE = 'marketing_example', 'Conteúdo de marketing aprovado'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='memory_items')
    kind = models.CharField(max_length=24, choices=Kind.choices)
    title = models.CharField(max_length=160, blank=True, default='')
    text = EncryptedTextField()                         # já mascarado (sem CPF/e-mail/telefone) quando vem de documentos
    payload = EncryptedJSONField(default=dict, blank=True)   # ex.: o JSON final aprovado de uma leitura
    embedding = EncryptedJSONField(default=list, blank=True)
    source = models.CharField(max_length=60, blank=True, default='')   # ex.: "document:12"
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization', 'kind', '-created_at'])]


class AIFeedback(models.Model):
    """O que a pessoa fez com uma sugestão da IA: o sinal mais valioso para medir confiança e propor regras."""

    class Decision(models.TextChoices):
        APPROVED = 'approved', 'Aprovou sem editar'
        EDITED = 'edited', 'Editou e aprovou'
        REJECTED = 'rejected', 'Rejeitou'
        UNDONE = 'undone', 'Desfez depois'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='ai_feedback')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action_kind = models.CharField(max_length=40, db_index=True)       # ver brain.autonomy.ACTION_KINDS
    decision = models.CharField(max_length=10, choices=Decision.choices)
    subject = models.CharField(max_length=60, blank=True, default='')  # ex.: "document:12"
    changes = EncryptedJSONField(default=list, blank=True)            # [{"field": "tipo_documento", "from": "OUTRO", "to": "INTIMACAO"}]
    confidence = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organization', 'action_kind', '-created_at'])]


class OfficeRule(models.Model):
    """Regra do escritório. Nasce como PROPOSTA (o sistema viu o padrão); só vale depois que um advogado aprova. Sempre visível e desligável."""

    class Status(models.TextChoices):
        PROPOSED = 'proposed', 'Proposta'
        ACTIVE = 'active', 'Ativa'
        REJECTED = 'rejected', 'Rejeitada'
        DISABLED = 'disabled', 'Desligada'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='office_rules')
    kind = models.CharField(max_length=24, default='field_correction')
    field = models.CharField(max_length=60)
    from_value = models.CharField(max_length=120)
    to_value = models.CharField(max_length=120)
    evidence = models.PositiveIntegerField(default=0)           # quantas correções iguais motivaram a proposta
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['organization', 'kind', 'field', 'from_value', 'to_value'], name='uniq_office_rule')]

    def describe(self):
        return f'Quando a leitura trouxer {self.field} = "{self.from_value}", trocar por "{self.to_value}".'


class AutonomyLevel(models.Model):
    """Matriz de autonomia: nível por tipo de ação e escritório. Ver brain/autonomy.py (R4 nunca é automático)."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='autonomy_levels')
    action_kind = models.CharField(max_length=40)
    mode = models.CharField(max_length=12, default='review')       # off | review | auto_undo | auto
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'action_kind'], name='uniq_autonomy_level')]


class AutonomyProposal(models.Model):
    """Sugestão de subir a autonomia de uma ação (critérios objetivos atingidos). Quem decide é o sócio."""

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        APPROVED = 'approved', 'Aprovada'
        REJECTED = 'rejected', 'Recusada'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='autonomy_proposals')
    action_kind = models.CharField(max_length=40)
    from_mode = models.CharField(max_length=12)
    to_mode = models.CharField(max_length=12)
    samples = models.PositiveIntegerField()
    approval_rate = models.DecimalField(max_digits=5, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class AutomationSuggestion(models.Model):
    """Fase E (CAD-174): a IA nota um padrão no escritório e sugere uma regra pronta. A pessoa aceita (vira regra DESLIGADA,
    que ela simula e liga), ou dispensa (não volta a sugerir por 60 dias; vira sinal negativo)."""

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        ACCEPTED = 'accepted', 'Aceita'
        DISMISSED = 'dismissed', 'Dispensada'

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='automation_suggestions')
    key = models.CharField(max_length=80)                    # detector + variante (ex.: "template:prazo_lembrete")
    title = models.CharField(max_length=160)
    reason = EncryptedTextField()                            # por que sugerimos (pode citar título de tarefa do escritório)
    evidence = models.PositiveIntegerField(default=0)
    payload = EncryptedJSONField(default=dict, blank=True)   # {"template": "..."} ou {"rule": {...}}
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    rule = models.ForeignKey('automations.Rule', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['organization', 'key'], name='uniq_suggestion_per_org')]


class OfficeProfile(models.Model):
    """Perfil do escritório (CAD-174): o que a IA usa para falar "do jeito do escritório" em minutas, marketing e triagem.
    Parte é editada pelo escritório (áreas, tom, assinatura, público) e parte é calculada dos dados (``auto_stats``)."""

    class Tone(models.TextChoices):
        FORMAL = 'formal', 'Formal'
        PROXIMO = 'proximo', 'Próximo e acolhedor'
        DIDATICO = 'didatico', 'Didático'

    organization = models.OneToOneField('accounts.Organization', on_delete=models.CASCADE, related_name='office_profile')
    areas = models.JSONField(default=list, blank=True)          # ["trabalhista", "previdenciario"]
    audience = models.CharField(max_length=200, blank=True, default='')   # público que o escritório atende
    city = models.CharField(max_length=80, blank=True, default='')
    tone = models.CharField(max_length=10, choices=Tone.choices, default=Tone.FORMAL)
    signature = models.TextField(blank=True, default='')        # assinatura padrão das minutas
    social = models.JSONField(default=dict, blank=True)         # {"instagram": "@...", "site": "https://..."}
    auto_stats = models.JSONField(default=dict, blank=True)     # calculado: tribunais, tipos de documento, volumes
    updated_at = models.DateTimeField(auto_now=True)
