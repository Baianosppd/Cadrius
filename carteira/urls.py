from django.urls import path

from carteira import api

urlpatterns = [
    path('oportunidades/', api.OpportunitiesView.as_view(), name='crm-opportunities'),
    path('oportunidades/<int:pk>/', api.OpportunityDetailView.as_view(), name='crm-opportunity'),
    path('contratos/', api.AgreementsView.as_view(), name='crm-agreements'),
    path('contratos/<int:pk>/', api.AgreementDetailView.as_view(), name='crm-agreement'),
    path('contratos/<int:pk>/<str:action>/', api.AgreementDetailView.as_view(), name='crm-agreement-action'),
    path('lancamentos/', api.ReceivablesView.as_view(), name='finance-receivables'),
    path('lancamentos/<int:pk>/<str:action>/', api.ReceivableActionView.as_view(), name='finance-receivable-action'),
    path('despesas/', api.ExpensesView.as_view(), name='finance-expenses'),
    path('despesas/<int:pk>/', api.ExpenseDetailView.as_view(), name='finance-expense'),
    path('painel/', api.SummaryView.as_view(), name='finance-summary'),
    path('clientes/<int:pk>/', api.ClientView.as_view(), name='crm-client'),
    path('asaas/webhook-config/', api.AsaasWebhookConfigView.as_view(), name='finance-asaas-config'),
    path('asaas/webhook/<int:conn_id>/', api.AsaasWebhookView.as_view(), name='finance-asaas-webhook'),
]
