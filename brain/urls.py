from django.urls import path

from brain import api

urlpatterns = [
    path('approvals/', api.ApprovalsView.as_view(), name='brain-approvals'),
    path('rules/', api.RulesView.as_view(), name='brain-rules'),
    path('rules/<int:pk>/decide/', api.RuleDecideView.as_view(), name='brain-rule-decide'),
    path('autonomy/', api.AutonomyView.as_view(), name='brain-autonomy'),
    path('autonomy/proposals/<int:pk>/decide/', api.ProposalDecideView.as_view(), name='brain-proposal-decide'),
    path('autonomy/<str:kind>/', api.AutonomySetView.as_view(), name='brain-autonomy-set'),
    path('memory/', api.MemoryView.as_view(), name='brain-memory'),
    path('memory/search/', api.MemorySearchView.as_view(), name='brain-memory-search'),
    path('memory/<int:pk>/', api.MemoryItemView.as_view(), name='brain-memory-item'),
]
