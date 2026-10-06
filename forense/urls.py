from django.urls import path

from forense import api

urlpatterns = [
    path('prazo/', api.PrazoView.as_view(), name='forense-prazo'),
    path('feriados/', api.HolidayListView.as_view(), name='forense-feriados'),
    path('feriados/<int:pk>/', api.HolidayDetailView.as_view(), name='forense-feriado'),
    path('suspensoes/', api.CourtSuspensionsView.as_view(), name='forense-suspensoes'),          # CAD-223
    path('tribunais/', api.CourtDirectoryView.as_view(), name='forense-tribunais'),
]

staff_urlpatterns = [
    path('forense/suspensoes/', api.StaffSuspensionsView.as_view(), name='staff-forense-suspensoes'),
    path('forense/suspensoes/<int:pk>/', api.StaffSuspensionDetailView.as_view(), name='staff-forense-suspensao'),
    path('forense/tribunais/', api.StaffCourtInfoView.as_view(), name='staff-forense-tribunais'),
]
