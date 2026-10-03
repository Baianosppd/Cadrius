from django.urls import path

from privacy import views

urlpatterns = [
    path('legal/documents/', views.CurrentDocumentsView.as_view(), name='legal-documents'),
    path('legal/subprocessors/', views.SubprocessorListView.as_view(), name='legal-subprocessors'),
    path('legal/consents/', views.ConsentCreateView.as_view(), name='legal-consent-create'),
    path('legal/consents/me/', views.MyConsentsView.as_view(), name='legal-consents-me'),
    path('privacy/requests/', views.PrivacyRequestListCreateView.as_view(), name='privacy-requests'),
    path('privacy/me/export/', views.MyDataExportView.as_view(), name='privacy-export'),
    path('privacy/organization/close/', views.OrganizationClosureView.as_view(), name='privacy-org-close'),
]
