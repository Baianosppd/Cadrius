from django.urls import path

from backoffice import api

urlpatterns = [
    path('me/', api.MeView.as_view(), name='bo-me'),
    path('overview/', api.OverviewView.as_view(), name='bo-overview'),
    path('health/', api.HealthView.as_view(), name='bo-health'),
    path('ai-switch/', api.AISwitchView.as_view(), name='bo-ai-switch'),
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
]
