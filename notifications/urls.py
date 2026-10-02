from django.urls import path

from .views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
)

urlpatterns = [
    path("", NotificationListView.as_view(), name="notifications"),
    path("unread-count/", NotificationUnreadCountView.as_view(), name="notifications-unread-count"),
    path("read-all/", NotificationMarkAllReadView.as_view(), name="notifications-read-all"),
    path("<int:pk>/read/", NotificationMarkReadView.as_view(), name="notifications-read"),
]
