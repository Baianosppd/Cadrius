from django.urls import path

from portal import api

urlpatterns = [
    path('links/', api.LinksView.as_view(), name='portal-links'),
    path('links/<int:pk>/revogar/', api.RevokeView.as_view(), name='portal-link-revoke'),
    path('acesso/<str:token>/', api.AccessView.as_view(), name='portal-access'),
]
