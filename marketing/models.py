"""Marketing (CAD-174): conteúdo, calendário editorial e campanhas — para os escritórios (dentro das regras da OAB,
Provimento 205/2021) e para a própria Cadrius (Gestão → Marketing).

``scope='escritorio'``: conteúdo do escritório (organization obrigatória). ``scope='cadrius'``: conteúdo da Cadrius (sem organization).
Conteúdo de marketing é público por natureza; não guardamos dados de clientes aqui (o verificador alerta se aparecer CPF/telefone)."""
from django.conf import settings
from django.db import models

from core.utils import EncryptedTextField


class Campaign(models.Model):
    class Scope(models.TextChoices):
        ESCRITORIO = 'escritorio', 'Escritório'
        CADRIUS = 'cadrius', 'Cadrius'

    scope = models.CharField(max_length=12, choices=Scope.choices, default=Scope.ESCRITORIO)
    organization = models.ForeignKey('accounts.Organization', null=True, blank=True, on_delete=models.CASCADE, related_name='campaigns')
    name = models.CharField(max_length=120)
    goal = models.CharField(max_length=300, blank=True, default='')        # objetivo (ex.: "autoridade em direito previdenciário")
    audience = models.CharField(max_length=200, blank=True, default='')
    channels = models.JSONField(default=list, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class ContentPiece(models.Model):
    class Scope(models.TextChoices):
        ESCRITORIO = 'escritorio', 'Escritório'
        CADRIUS = 'cadrius', 'Cadrius'

    class Channel(models.TextChoices):
        INSTAGRAM = 'instagram', 'Instagram'
        FACEBOOK = 'facebook', 'Facebook'
        LINKEDIN = 'linkedin', 'LinkedIn'
        BLOG = 'blog', 'Blog / site'
        GOOGLE = 'google_business', 'Perfil no Google'
        NEWSLETTER = 'newsletter', 'Newsletter (e-mail)'
        VIDEO = 'video_curto', 'Vídeo curto (Reels/Shorts)'

    class Status(models.TextChoices):
        DRAFT = 'rascunho', 'Rascunho'
        APPROVED = 'aprovado', 'Aprovado'
        SCHEDULED = 'agendado', 'Agendado'
        PUBLISHED = 'publicado', 'Publicado'
        FAILED = 'falhou', 'Falhou'

    scope = models.CharField(max_length=12, choices=Scope.choices, default=Scope.ESCRITORIO, db_index=True)
    organization = models.ForeignKey('accounts.Organization', null=True, blank=True, on_delete=models.CASCADE, related_name='content_pieces')
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL, related_name='pieces')
    channel = models.CharField(max_length=20, choices=Channel.choices)
    theme = models.CharField(max_length=200)
    title = models.CharField(max_length=200, blank=True, default='')
    body = models.TextField(blank=True, default='')
    hashtags = models.JSONField(default=list, blank=True)
    image_hint = models.CharField(max_length=500, blank=True, default='')    # sugestão de imagem/arte
    image_url = models.URLField(max_length=500, blank=True, default='')      # imagem pública (Instagram exige)
    image_file = models.CharField(max_length=300, blank=True, default='')    # CAD-226: imagem gerada (armazenamento do Cadrius)
    image_source = models.CharField(max_length=10, blank=True, default='')   # gemini | marca | foto (openai: legado)
    # CAD-231: vídeo curto com IA (Gemini Veo, adicional de mídia). A geração é assíncrona no Google: guardamos a operação.
    video_file = models.CharField(max_length=300, blank=True, default='')
    video_status = models.CharField(max_length=10, blank=True, default='')   # '' | gerando | pronto | falhou
    video_error = models.CharField(max_length=300, blank=True, default='')
    video_op = models.CharField(max_length=300, blank=True, default='')
    video_started_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=120, blank=True, default='')
    publish_error = models.CharField(max_length=300, blank=True, default='')
    compliance = models.JSONField(default=list, blank=True)                  # alertas do verificador (OAB/LGPD)
    generated_body = models.TextField(blank=True, default='')                # versão entregue pelo Cadrius (mede edição)
    ai_provider = models.CharField(max_length=16, blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_at', '-created_at']
        indexes = [models.Index(fields=['scope', 'organization', 'status'])]


class MarketingAsset(models.Model):
    """Foto ou imagem que o escritório sobe para usar nos conteúdos (CAD-231): fundo das artes prontas (todos os planos) e
    referência para a IA de imagem/vídeo (adicional de mídia). Validada e regravada pelo Pillow (sem EXIF/localização)."""

    scope = models.CharField(max_length=12, choices=ContentPiece.Scope.choices, default=ContentPiece.Scope.ESCRITORIO)
    organization = models.ForeignKey('accounts.Organization', null=True, blank=True, on_delete=models.CASCADE,
                                     related_name='marketing_assets')
    name = models.CharField(max_length=120, blank=True, default='')
    file = models.CharField(max_length=300)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class CaptureForm(models.Model):
    """Formulário público de captação do escritório (CAD-223): vira contato + oportunidade no funil, com consentimento LGPD.

    Texto informativo (Provimento OAB 205/2021): o verificador de marketing roda no título e na apresentação ao salvar."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='capture_forms')
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL, related_name='forms')
    token = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=120)
    intro = models.CharField(max_length=500, blank=True, default='')
    areas = models.JSONField(default=list, blank=True)                       # opções de "assunto" (ex.: Previdenciário)
    thank_you = models.CharField(max_length=300, blank=True, default='Recebemos sua mensagem. Retornaremos em breve.')
    active = models.BooleanField(default=True)
    compliance = models.JSONField(default=list, blank=True)
    submissions = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class SatisfactionSurvey(models.Model):
    """Pesquisa de satisfação (NPS) enviada a um cliente por automação (CAD-223). Resposta só pelo link único."""

    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE, related_name='surveys')
    contact = models.ForeignKey('contacts.Contact', on_delete=models.CASCADE, related_name='surveys')
    token = models.CharField(max_length=40, unique=True)
    reason = models.CharField(max_length=120, blank=True, default='')          # ex.: "Contrato concluído"
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    comment = EncryptedTextField(blank=True, default='')                         # opinião do cliente: cifrada
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def category(self) -> str:
        if self.score is None:
            return ''
        return 'promotor' if self.score >= 9 else ('neutro' if self.score >= 7 else 'detrator')
