from django.urls import path

from erp import api

urlpatterns = [
    path('presets/', api.PresetsView.as_view(), name='erp-presets'),
    path('connectors/', api.ConnectorListView.as_view(), name='erp-connectors'),
    path('connectors/<int:pk>/', api.ConnectorDetailView.as_view(), name='erp-connector'),
    path('connectors/<int:pk>/run/', api.RunOperationView.as_view(), name='erp-run'),
]
