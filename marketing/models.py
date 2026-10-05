"""Marketing (CAD-174): conteúdo, calendário editorial e campanhas — para os escritórios (dentro das regras da OAB,
Provimento 205/2021) e para a própria Cadrius (Gestão → Marketing).

``scope='escritorio'``: conteúdo do escritório (organization obrigatória). ``scope='cadrius'``: conteúdo da Cadrius (sem organization).
Conteúdo de marketing é público por natureza; não guardamos dados de clientes aqui (o verificador alerta se aparecer CPF/telefone)."""
from django.conf import settings
from django.db import models


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
