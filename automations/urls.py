from django.urls import path

from automations import api

urlpatterns = [
    path('catalog/', api.CatalogView.as_view(), name='automation-catalog'),
    path('templates/', api.TemplateListView.as_view(), name='automation-templates'),
    path('rules/', api.RuleListView.as_view(), name='automation-rules'),
    path('rules/<int:pk>/', api.RuleDetailView.as_view(), name='automation-rule'),
    path('rules/<int:pk>/simulate/', api.RuleSimulateView.as_view(), name='automation-rule-simulate'),
    path('rules/<int:pk>/enable/', api.RuleEnableView.as_view(), name='automation-rule-enable'),
    path('rules/<int:pk>/atalho/', api.RuleShortcutView.as_view(), name='automation-rule-shortcut'),           # CAD-226
    path('runs/', api.RunListView.as_view(), name='automation-runs'),
    path('runs/<int:pk>/approve/', api.RunDecisionView.as_view(decision='approve'), name='automation-run-approve'),
    path('runs/<int:pk>/reject/', api.RunDecisionView.as_view(decision='reject'), name='automation-run-reject'),
    path('conformidade/', api.ComplianceView.as_view(), name='automation-compliance'),            # CAD-223
]
