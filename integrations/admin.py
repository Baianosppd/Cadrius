from django.contrib import admin
from .models import AppConnection, IntegrationLog

@admin.register(AppConnection)
class AppConnectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'app_name', 'user', 'is_active', 'created_at')
    list_filter = ('app_name', 'is_active', 'user')

@admin.register(IntegrationLog)
class IntegrationLogAdmin(admin.ModelAdmin):
    list_display = ('connection', 'status', 'attempted_at')
    list_filter = ('status', 'connection')