from django.urls import path
from .views import WebhookReceiverView

urlpatterns = [
    
    path('receive/<uuid:connection_id>/', WebhookReceiverView.as_view(), name='webhook_receive'),
]