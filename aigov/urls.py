from django.urls import path

from aigov import views

urlpatterns = [
    path('policy/', views.PolicyView.as_view(), name='ai-policy'),
    path('activity/', views.ActivityView.as_view(), name='ai-activity'),
    path('workflows/', views.CreateAIWorkflowDraftView.as_view(), name='ai-workflow-draft'),
    path('executions/pending/', views.PendingExecutionsView.as_view(), name='ai-executions-pending'),
    path('executions/<int:pk>/review/', views.ReviewExecutionView.as_view(), name='ai-execution-review'),
]
