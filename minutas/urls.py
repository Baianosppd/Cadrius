from django.urls import path

from minutas import api

urlpatterns = [
    path('', api.DraftListView.as_view(), name='minutas'),
    path('<int:pk>/', api.DraftDetailView.as_view(), name='minuta'),
    path('<int:pk>/docx/', api.DraftDocxView.as_view(), name='minuta-docx'),
    path('modelos/', api.TemplateListView.as_view(), name='minuta-modelos'),
    path('modelos/importar/', api.TemplateImportView.as_view(), name='minuta-modelo-importar'),   # CAD-231
    path('modelos/<int:pk>/', api.TemplateDetailView.as_view(), name='minuta-modelo'),
]
