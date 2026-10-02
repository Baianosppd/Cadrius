from django.urls import path

from audit import views

urlpatterns = [
    path('events/', views.AuditEventListView.as_view(), name='audit-events'),
    path('events/export/', views.AuditEventExportView.as_view(), name='audit-events-export'),
    path('summary/', views.AuditSummaryView.as_view(), name='audit-summary'),
    path('alerts/', views.AlertListView.as_view(), name='audit-alerts'),
    path('alerts/<int:pk>/', views.AlertReviewView.as_view(), name='audit-alert-review'),
]
