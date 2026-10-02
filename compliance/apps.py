from django.apps import AppConfig


class ComplianceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'compliance'
    verbose_name = 'Conformidade (ISO 27001/27701 e LGPD)'
