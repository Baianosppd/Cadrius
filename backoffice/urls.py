from django.urls import path

from aigov import staff_api as ai_staff

from backoffice import api

urlpatterns = [
    path('me/', api.MeView.as_view(), name='bo-me'),
    path('overview/', api.OverviewView.as_view(), name='bo-overview'),
    path('health/', api.HealthView.as_view(), name='bo-health'),
    path('ai-switch/', api.AISwitchView.as_view(), name='bo-ai-switch'),
    path('ia/rotas/', ai_staff.RoutesView.as_view(), name='bo-ai-routes'),                      # CAD-224
    path('ia/rotas/<str:activity>/', ai_staff.RouteDetailView.as_view(), name='bo-ai-route'),
    path('cyber/', api.CyberView.as_view(), name='bo-cyber'),
    path('cyber/blocked-ips/', api.BlockedIPView.as_view(), name='bo-cyber-block'),
    path('cyber/blocked-ips/<int:pk>/', api.BlockedIPView.as_view(), name='bo-cyber-unblock'),
    path('cyber/alerts/<int:pk>/review/', api.AlertReviewView.as_view(), name='bo-cyber-alert'),
    path('organizations/', api.OrganizationListView.as_view(), name='bo-orgs'),
    path('organizations/<uuid:pk>/', api.OrganizationDetailView.as_view(), name='bo-org'),
    path('organizations/<uuid:pk>/actions/', api.OrganizationActionView.as_view(), name='bo-org-action'),
    path('users/', api.UserListView.as_view(), name='bo-users'),
    path('users/<uuid:pk>/actions/', api.UserActionView.as_view(), name='bo-user-action'),
    path('staff/', api.StaffListView.as_view(), name='bo-staff'),
    path('staff/<uuid:pk>/', api.StaffDetailView.as_view(), name='bo-staff-detail'),
    path('fiscal/payments/', api.FiscalPaymentsView.as_view(), name='bo-fiscal-payments'),
    path('fiscal/payments/export.csv', api.FiscalExportView.as_view(), name='bo-fiscal-export'),
    path('fiscal/payments/<int:pk>/invoice/', api.FiscalInvoiceView.as_view(), name='bo-fiscal-invoice'),
    path('fiscal/payments/<int:pk>/nfse/', api.FiscalNfseView.as_view(), name='bo-fiscal-nfse'),
    path('fiscal/obligations/', api.FiscalObligationsView.as_view(), name='bo-fiscal-obligations'),
    path('fiscal/obligations/<int:pk>/done/', api.FiscalObligationDoneView.as_view(), name='bo-fiscal-obligation-done'),
]
