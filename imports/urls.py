from django.urls import path

from imports import api

urlpatterns = [
    path('', api.ImportListView.as_view(), name='imports'),
    path('<int:pk>/', api.ImportDetailView.as_view(), name='import-detail'),
    path('<int:pk>/preview/', api.ImportPreviewView.as_view(), name='import-preview'),
    path('<int:pk>/commit/', api.ImportCommitView.as_view(), name='import-commit'),
]
