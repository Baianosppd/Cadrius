from django.urls import path

from compliance import api, views

urlpatterns = [
    path('', views.overview, name='sc-overview'),
    path('events/', views.events, name='sc-events'),
    path('events/verify/', views.verify_chain_view, name='sc-verify-chain'),
    path('alerts/', views.alerts, name='sc-alerts'),
    path('alerts/<int:pk>/review/', views.alert_review, name='sc-alert-review'),
    path('posture/', views.posture, name='sc-posture'),
    path('ai/', views.ai_governance, name='sc-ai'),
    path('ai/switch/', views.ai_switch, name='sc-ai-switch'),
    path('privacy/', views.privacy_ops, name='sc-privacy'),
    path('ropa/', views.ropa, name='sc-ropa'),
    path('assess/', views.assess, name='sc-assess'),
    path('<str:framework>/export.csv', views.framework_csv, name='sc-framework-csv'),
    path('<str:framework>/', views.framework, name='sc-framework'),
]

api_urlpatterns = [
    path('overview/', api.OverviewApi.as_view(), name='security-api-overview'),
    path('controls/', api.ControlsApi.as_view(), name='security-api-controls'),
    path('checks/', api.ChecksApi.as_view(), name='security-api-checks'),
    path('ropa/', api.RopaApi.as_view(), name='security-api-ropa'),
]
