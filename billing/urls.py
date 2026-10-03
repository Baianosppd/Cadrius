from django.urls import path
from .views import CreateCheckoutSessionView, CurrentPlanView, StripeWebhookView, PlansListView

urlpatterns = [
    path('plans/', PlansListView.as_view(), name='billing-plans'),
    path('plans/current/', CurrentPlanView.as_view(), name='billing-current-plan'),
    # Front-end usa esta:
    path('checkout/', CreateCheckoutSessionView.as_view(), name='stripe-checkout'),
    
    # O Stripe (robô) usa esta:
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
]