from django.apps import AppConfig


class GcalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gcal'
    verbose_name = 'Google Calendar'

    def ready(self):
        from gcal import signals  # noqa: F401
