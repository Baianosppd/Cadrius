from django.urls import path

from integrations import api_v1

urlpatterns = [
    path('catalog/', api_v1.CatalogView.as_view(), name='integrations-catalog'),
    path('connections/<int:pk>/test/', api_v1.TestConnectionView.as_view(), name='integrations-test'),
    path('signature/', api_v1.SignatureView.as_view(), name='integrations-signature'),
    path('charge/', api_v1.ChargeView.as_view(), name='integrations-charge'),
]
