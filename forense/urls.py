from django.urls import path

from forense import api

urlpatterns = [
    path('prazo/', api.PrazoView.as_view(), name='forense-prazo'),
    path('feriados/', api.HolidayListView.as_view(), name='forense-feriados'),
    path('feriados/<int:pk>/', api.HolidayDetailView.as_view(), name='forense-feriado'),
]
