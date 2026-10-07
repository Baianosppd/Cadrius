from django.urls import path

from marketing import api, api_leads

urlpatterns = [
    path('ideias/', api.IdeasView.as_view(), name='mkt-ideas'),
    path('verificar/', api.CheckView.as_view(), name='mkt-check'),
    path('conteudos/', api.PieceListView.as_view(), name='mkt-pieces'),
    path('conteudos/<int:pk>/', api.PieceDetailView.as_view(), name='mkt-piece'),
    path('conteudos/<int:pk>/publicar/', api.PiecePublishView.as_view(), name='mkt-piece-publish'),
    path('conteudos/<int:pk>/imagem/', api.PieceImageView.as_view(), name='mkt-piece-image'),                 # CAD-226
    path('campanhas/', api.CampaignListView.as_view(), name='mkt-campaigns'),
    path('campanhas/<int:pk>/', api.CampaignDetailView.as_view(), name='mkt-campaign'),
    path('formularios/', api_leads.FormListView.as_view(), name='mkt-forms'),                      # CAD-223
    path('formularios/<int:pk>/', api_leads.FormDetailView.as_view(), name='mkt-form'),
    path('resultados/', api_leads.ResultsView.as_view(), name='mkt-results'),
]

public_urlpatterns = [
    path('captacao/<str:token>/', api_leads.PublicFormView.as_view(), name='public-capture'),
    path('pesquisa/<str:token>/', api_leads.PublicSurveyView.as_view(), name='public-survey'),
    path('marketing/imagem/<str:token>/', api.PublicImageView.as_view(), name='public-mkt-image'),
]

staff_urlpatterns = [
    path('marketing/ideias/', api.StaffIdeasView.as_view(), name='staff-mkt-ideas'),
    path('marketing/verificar/', api.StaffCheckView.as_view(), name='staff-mkt-check'),
    path('marketing/conteudos/', api.StaffPieceListView.as_view(), name='staff-mkt-pieces'),
    path('marketing/conteudos/<int:pk>/', api.StaffPieceDetailView.as_view(), name='staff-mkt-piece'),
    path('marketing/conteudos/<int:pk>/publicar/', api.StaffPiecePublishView.as_view(), name='staff-mkt-piece-publish'),
    path('marketing/conteudos/<int:pk>/imagem/', api.StaffPieceImageView.as_view(), name='staff-mkt-piece-image'),
    path('marketing/campanhas/', api.StaffCampaignListView.as_view(), name='staff-mkt-campaigns'),
    path('marketing/campanhas/<int:pk>/', api.StaffCampaignDetailView.as_view(), name='staff-mkt-campaign'),
    path('marketing/crescimento/', api.GrowthView.as_view(), name='staff-mkt-growth'),
]
