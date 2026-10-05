from django.urls import path

from support import api

urlpatterns = [
    path('tickets/', api.TicketListView.as_view(), name='support-tickets'),
    path('tickets/<int:pk>/', api.TicketDetailView.as_view(), name='support-ticket'),
    path('tickets/<int:pk>/messages/', api.TicketMessageView.as_view(), name='support-ticket-messages'),
    path('tickets/<int:pk>/status/', api.TicketStatusView.as_view(), name='support-ticket-status'),
    path('tickets/<int:pk>/access/', api.TicketAccessView.as_view(), name='support-ticket-access'),
]

staff_urlpatterns = [
    path('support/tickets/', api.StaffTicketListView.as_view(), name='bo-support-tickets'),
    path('support/tickets/<int:pk>/', api.StaffTicketDetailView.as_view(), name='bo-support-ticket'),
]
