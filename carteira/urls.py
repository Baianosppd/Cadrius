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
    path('financeiro/config/', api.FinanceSettingsView.as_view(), name='finance-settings'),          # CAD-223
    path('financeiro/recorrentes/', api.RecurringView.as_view(), name='finance-recurring'),
    path('financeiro/recorrentes/<int:pk>/', api.RecurringDetailView.as_view(), name='finance-recurring-detail'),
    path('financeiro/fluxo/', api.CashFlowView.as_view(), name='finance-cashflow'),
    path('financeiro/indicadores/', api.IndicatorsView.as_view(), name='finance-indicators'),
    path('financeiro/fiscal/', api.OfficeFiscalView.as_view(), name='finance-fiscal'),
    path('financeiro/contador.csv', api.AccountantExportView.as_view(), name='finance-accountant'),
    path('painel/', api.SummaryView.as_view(), name='finance-summary'),
    path('clientes/<int:pk>/', api.ClientView.as_view(), name='crm-client'),
    path('asaas/webhook-config/', api.AsaasWebhookConfigView.as_view(), name='finance-asaas-config'),
    path('asaas/webhook/<int:conn_id>/', api.AsaasWebhookView.as_view(), name='finance-asaas-webhook'),
]
