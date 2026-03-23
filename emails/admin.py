from django.contrib import admin
from .models import MailBox, EmailMessage

@admin.register(MailBox)
class MailBoxAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'imap_host', 'username', 'last_fetch_at', 'is_active')
    list_filter = ('is_active', 'user')
    search_fields = ('name', 'username', 'imap_host')

@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    # 'status' substituído por 'is_dispatched'
    list_display = ('id', 'subject', 'sender', 'mailbox', 'is_dispatched', 'received_at')
    list_filter = ('is_dispatched', 'mailbox', 'received_at')
    search_fields = ('subject', 'sender', 'body_text', 'message_id')
    
    # 'updated_at' removido daqui e também o método get_readonly_fields (pois extracted_data não existe mais no email)
    readonly_fields = ('created_at', 'received_at')
    date_hierarchy = 'received_at'