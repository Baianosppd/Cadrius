from django.contrib import admin
from .models import MailBox, EmailMessage, AutomationRule

@admin.register(MailBox)
class MailBoxAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'imap_host', 'username', 'last_fetch_at', 'is_active')
    list_filter = ('is_active', 'user')
    search_fields = ('name', 'username', 'imap_host')

@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'sender', 'mailbox', 'status', 'received_at')
    list_filter = ('status', 'mailbox', 'received_at')
    search_fields = ('subject', 'sender', 'body_text', 'message_id')
    readonly_fields = ('created_at', 'updated_at', 'received_at')
    date_hierarchy = 'received_at'
    
    # Mostra o JSON extraído de forma bonita no admin
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ('extracted_data',)
        return self.readonly_fields

@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'mailbox', 'priority', 'is_active')
    list_filter = ('is_active', 'user', 'mailbox')
    search_fields = ('name', 'subject_contains', 'sender_contains')
    ordering = ('priority',)