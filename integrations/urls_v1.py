from django.urls import path

from integrations import api_v1, api_whatsapp

urlpatterns = [
    path('whatsapp/', api_whatsapp.WhatsAppStatusView.as_view(), name='whatsapp-status'),                 # CAD-225
    path('whatsapp/conectar/', api_whatsapp.WhatsAppConnectView.as_view(), name='whatsapp-connect'),
    path('whatsapp/link/', api_whatsapp.WhatsAppLinkView.as_view(), name='whatsapp-link'),
    path('whatsapp/desconectar/', api_whatsapp.WhatsAppDisconnectView.as_view(), name='whatsapp-disconnect'),
    path('catalog/', api_v1.CatalogView.as_view(), name='integrations-catalog'),
    path('connections/<int:pk>/test/', api_v1.TestConnectionView.as_view(), name='integrations-test'),
    path('signature/', api_v1.SignatureView.as_view(), name='integrations-signature'),
    path('charge/', api_v1.ChargeView.as_view(), name='integrations-charge'),
]
