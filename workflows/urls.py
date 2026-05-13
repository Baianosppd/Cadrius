from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import GenerateWorkflowView, WorkflowViewSet
from .webhooks import WebhookReceiverView, catch_webhook_event

router = DefaultRouter()
router.register(r'automations', WorkflowViewSet, basename='workflow')

urlpatterns = [
    # Rotas do Front-end (React)
    path('', include(router.urls)),
    path('generate/', GenerateWorkflowView.as_view(), name='workflow_generate'),

    # Webhook externo por UUID na URL (token = ``Trigger.webhook_token``)
    path(
        "webhooks/catch/<uuid:token>/",
        catch_webhook_event,
        name="workflow_webhook_catch",
    ),

    # Rota pública para os sistemas externos (Trello, WhatsApp, ERPs)
    path('webhook/inbound/<int:connection_id>/', WebhookReceiverView.as_view(), name='webhook_receiver'),
]