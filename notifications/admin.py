from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "type", "title", "read_at", "created_at")
    list_filter = ("type", "read_at")
    search_fields = ("title", "description", "user__email")
    raw_id_fields = ("user", "organization")
