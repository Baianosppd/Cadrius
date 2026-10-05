from django.contrib import admin

from publications.models import OabWatch


@admin.register(OabWatch)
class OabWatchAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'organization', 'is_active', 'last_checked_at', 'last_error')
