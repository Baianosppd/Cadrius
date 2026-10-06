from django.urls import path

from contacts import api

urlpatterns = [
    path('', api.ContactListView.as_view(), name='contacts'),
    path('<int:pk>/', api.ContactDetailView.as_view(), name='contact-detail'),
    path('cnpj/<str:cnpj>/', api.CnpjLookupView.as_view(), name='contact-cnpj'),          # CAD-223
]
