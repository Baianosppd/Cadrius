from django.urls import path

from assistant import api, plugins_api

urlpatterns = [
    path('status/', api.StatusView.as_view(), name='assistant-status'),
    path('conversations/', api.ConversationListView.as_view(), name='assistant-conversations'),
    path('conversations/<int:pk>/', api.ConversationDetailView.as_view(), name='assistant-conversation'),
    path('actions/<int:pk>/decide/', api.ActionDecideView.as_view(), name='assistant-action-decide'),
    path('write/', api.WriteView.as_view(), name='assistant-write'),
    path('settings/', api.SettingsView.as_view(), name='assistant-settings'),
    path('plugins/', plugins_api.PluginsView.as_view(), name='assistant-plugins'),
    path('plugins/tokens/', plugins_api.TokenCreateView.as_view(), name='assistant-token-create'),
    path('plugins/tokens/<int:pk>/', plugins_api.TokenRevokeView.as_view(), name='assistant-token-revoke'),
    path('plugins/keys/', plugins_api.KeyView.as_view(), name='assistant-keys'),
    path('plugins/keys/test/', plugins_api.KeyTestView.as_view(), name='assistant-key-test'),
]
