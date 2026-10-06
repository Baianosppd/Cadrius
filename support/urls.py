from django.urls import path

from support import api

urlpatterns = [
    path('tickets/', api.TicketListView.as_view(), name='support-tickets'),
    path('tickets/<int:pk>/', api.TicketDetailView.as_view(), name='support-ticket'),
    path('tickets/<int:pk>/messages/', api.TicketMessageView.as_view(), name='support-ticket-messages'),
    path('tickets/<int:pk>/status/', api.TicketStatusView.as_view(), name='support-ticket-status'),
    path('tickets/<int:pk>/access/', api.TicketAccessView.as_view(), name='support-ticket-access'),
    path('parametrizacoes/', api.CustomizationListView.as_view(), name='support-customizations'),               # CAD-223
    path('parametrizacoes/<int:pk>/<str:decision>/', api.CustomizationDecisionView.as_view(), name='support-customization-decide'),
]

staff_urlpatterns = [
    path('support/tickets/', api.StaffTicketListView.as_view(), name='bo-support-tickets'),
    path('support/tickets/<int:pk>/', api.StaffTicketDetailView.as_view(), name='bo-support-ticket'),
    path('support/parametrizacoes/', api.StaffCustomizationListView.as_view(), name='bo-support-customizations'),
    path('support/parametrizacoes/<int:pk>/', api.StaffCustomizationDetailView.as_view(), name='bo-support-customization'),
]
