from django.urls import path

from imports import api, folders_api

urlpatterns = [
    path('', api.ImportListView.as_view(), name='imports'),
    path('<int:pk>/', api.ImportDetailView.as_view(), name='import-detail'),
    path('<int:pk>/preview/', api.ImportPreviewView.as_view(), name='import-preview'),
    path('<int:pk>/commit/', api.ImportCommitView.as_view(), name='import-commit'),
    # CAD-234: carteira de clientes por pastas (Google Drive ou .zip)
    path('pastas/', folders_api.FolderImportListView.as_view(), name='folder-imports'),
    path('pastas/zip/', folders_api.FolderImportZipView.as_view(), name='folder-import-zip'),
    path('pastas/<int:pk>/', folders_api.FolderImportDetailView.as_view(), name='folder-import'),
    path('pastas/<int:pk>/importar/', folders_api.FolderImportRunView.as_view(), name='folder-import-run'),
]
