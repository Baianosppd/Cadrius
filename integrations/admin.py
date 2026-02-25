from django.contrib import admin
from .models import IntegrationConfig, IntegrationLog

@admin.register(IntegrationConfig)
class IntegrationConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'is_active', 'has_telegram', 'has_trello')
    list_filter = ('is_active', 'user')
    search_fields = ('name', 'user__email', 'user__username')

    # Helpers para ver rapidamente o que está configurado
    def has_telegram(self, obj):
        return bool(obj.telegram_bot_token and obj.telegram_chat_id)
    has_telegram.boolean = True
    has_telegram.short_description = 'Telegram?'

    def has_trello(self, obj):
        return bool(obj.trello_api_key and obj.trello_api_token)
    has_trello.boolean = True
    has_trello.short_description = 'Projuris/Trello?'

@admin.register(IntegrationLog)
class IntegrationLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'service', 'status', 'response_code', 'email_message_link', 'attempted_at')
    list_filter = ('service', 'status', 'attempted_at')
    search_fields = ('response_body', 'request_data')
    readonly_fields = ('attempted_at', 'request_data', 'response_body')
    
    # Link clicável para ir direto ao e-mail que gerou o log
    def email_message_link(self, obj):
        from django.utils.html import format_html
        from django.urls import reverse
        if obj.email_message:
            url = reverse('admin:emails_emailmessage_change', args=[obj.email_message.id])
            return format_html('<a href="{}">{}</a>', url, obj.email_message)
        return "-"
    email_message_link.short_description = "E-mail Origem"