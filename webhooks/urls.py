from django.urls import path
from .views import dynamic_webhook_receiver

urlpatterns = [
    
    path('<uuid:identifier>/', dynamic_webhook_receiver, name='webhook-receiver'),
]