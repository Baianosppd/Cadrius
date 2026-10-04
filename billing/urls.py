from django.urls import path
from .views import (CreateCheckoutSessionView, CreditPackCheckoutView, CreditPacksView, CurrentPlanView,
                    PlansListView, StripeWebhookView)

urlpatterns = [
    path('plans/', PlansListView.as_view(), name='billing-plans'),
    path('plans/current/', CurrentPlanView.as_view(), name='billing-current-plan'),
    # Front-end usa esta:
    path('checkout/', CreateCheckoutSessionView.as_view(), name='stripe-checkout'),
    
    path('credit-packs/', CreditPacksView.as_view(), name='billing-credit-packs'),
    path('credit-packs/checkout/', CreditPackCheckoutView.as_view(), name='billing-credit-pack-checkout'),

    # O Stripe (robô) usa esta:
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
]