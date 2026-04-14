from django.urls import path
from .views import CreateCheckoutSessionView, StripeWebhookView

urlpatterns = [
    # Front-end usa esta:
    path('checkout/', CreateCheckoutSessionView.as_view(), name='stripe-checkout'),
    
    # O Stripe (robô) usa esta:
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
]