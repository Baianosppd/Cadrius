from django.db import models
from workflows.models import Workflow
import uuid

# Create your models here.
class WebhookTrigger(models.Model):
    workflow = models.OneToOneField(Workflow, on_delete=models.CASCADE, related_name='webhook_trigger')
    # O <identifier> dinâmico da URL. Gerado automaticamente e indexado para buscas super rápidas.
    identifier = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    
    def __str__(self):
        return str(self.identifier)