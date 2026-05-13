from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WorkflowViewSet, WebhookReceiverView, GenerateWorkflowView

router = DefaultRouter()
router.register(r'automations', WorkflowViewSet, basename='workflow')

urlpatterns = [
    # Rotas do Front-end (React)
    path('', include(router.urls)),
    path('generate/', GenerateWorkflowView.as_view(), name='workflow_generate'),

    # Rota pública para os sistemas externos (Trello, WhatsApp, ERPs)
    path('webhook/inbound/<int:connection_id>/', WebhookReceiverView.as_view(), name='webhook_receiver'),
]