from django.urls import path

from publications import api

urlpatterns = [
    path('', api.PublicationListView.as_view(), name='publications'),
    path('<int:pk>/', api.PublicationDetailView.as_view(), name='publication'),
    path('<int:pk>/confirm/', api.PublicationActionView.as_view(action='confirm'), name='publication-confirm'),
    path('<int:pk>/discard/', api.PublicationActionView.as_view(action='discard'), name='publication-discard'),
    path('<int:pk>/reopen/', api.PublicationActionView.as_view(action='reopen'), name='publication-reopen'),
    path('<int:pk>/prazo/', api.PrazoPreviewView.as_view(), name='publication-prazo'),
    path('oabs/', api.WatchListView.as_view(), name='publication-watches'),
    path('oabs/<int:pk>/', api.WatchDetailView.as_view(), name='publication-watch'),
    path('oabs/<int:pk>/check-now/', api.WatchCheckNowView.as_view(), name='publication-watch-check'),
]
