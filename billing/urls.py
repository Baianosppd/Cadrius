from django.urls import include, path
from .admin_api import PriceHistoryView, SummaryView, router as admin_router
from .views import (BillingNoticesView, CreateCheckoutSessionView, CreditPackCheckoutView, CreditPacksView, CurrentPlanView,
                    PlansListView, PromotionValidateView, StripeWebhookView)

urlpatterns = [
    path('plans/', PlansListView.as_view(), name='billing-plans'),
    path('plans/current/', CurrentPlanView.as_view(), name='billing-current-plan'),
    # Front-end usa esta:
    path('checkout/', CreateCheckoutSessionView.as_view(), name='stripe-checkout'),
    
    path('credit-packs/', CreditPacksView.as_view(), name='billing-credit-packs'),
    path('credit-packs/checkout/', CreditPackCheckoutView.as_view(), name='billing-credit-pack-checkout'),

    path('promotions/validate/', PromotionValidateView.as_view(), name='billing-promo-validate'),
    path('notices/', BillingNoticesView.as_view(), name='billing-notices'),

    # Área administrativa do financeiro (só equipe Cadrius, is_staff)
    path('admin/summary/', SummaryView.as_view(), name='billing-admin-summary'),
    path('admin/price-history/', PriceHistoryView.as_view(), name='billing-admin-price-history'),
    path('admin/', include(admin_router.urls)),

    # O Stripe (robô) usa esta:
    path('webhook/', StripeWebhookView.as_view(), name='stripe-webhook'),
]