from django.urls import path

from assistant import api

urlpatterns = [
    path('status/', api.StatusView.as_view(), name='assistant-status'),
    path('conversations/', api.ConversationListView.as_view(), name='assistant-conversations'),
    path('conversations/<int:pk>/', api.ConversationDetailView.as_view(), name='assistant-conversation'),
    path('actions/<int:pk>/decide/', api.ActionDecideView.as_view(), name='assistant-action-decide'),
    path('write/', api.WriteView.as_view(), name='assistant-write'),
]
