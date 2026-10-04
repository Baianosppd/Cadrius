from django.urls import path

from gcal import api

urlpatterns = [
    path('', api.GCalStatusView.as_view(), name='gcal-status'),
    path('app/', api.GCalAppView.as_view(), name='gcal-app'),
    path('connect/', api.GCalConnectView.as_view(), name='gcal-connect'),
    path('callback/', api.GCalCallbackView.as_view(), name='gcal-callback'),
    path('disconnect/', api.GCalDisconnectView.as_view(), name='gcal-disconnect'),
    path('sync-now/', api.GCalSyncNowView.as_view(), name='gcal-sync-now'),
]
