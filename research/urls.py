from django.urls import path

from research import api

urlpatterns = [
    path('cases/', api.CaseListView.as_view(), name='research-cases'),
    path('cases/<int:pk>/', api.CaseDetailView.as_view(), name='research-case'),
    path('cases/<int:pk>/check-now/', api.CaseCheckNowView.as_view(), name='research-case-check'),
    path('news/', api.NewsView.as_view(), name='research-news'),
]
