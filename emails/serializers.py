from rest_framework import serializers
from emails.models import MailBox, EmailMessage
from extraction.models import ExtractionProfile

class MailBoxSerializer(serializers.ModelSerializer):
    class Meta:
        model = MailBox
        fields = ['id', 'name', 'imap_host', 'imap_port', 'username', 'is_active', 'last_fetch_at', 'user']
        read_only_fields = ['last_fetch_at', 'user']
        extra_kwargs = {
            'password': {'write_only': True}
        }


class ExtractionProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractionProfile
        fields = ['id', 'name', 'system_prompt_template', 'pydantic_schema_name', 'user']
        read_only_fields = ['user']

class EmailMessageSerializer(serializers.ModelSerializer):
    mailbox_name = serializers.CharField(source='mailbox.name', read_only=True)
    
    class Meta:
        model = EmailMessage
        fields = [
            'id', 'mailbox_name', 'subject', 'sender', 'received_at', 
            'is_dispatched', 'body_text', 'created_at'
        ]
        read_only_fields = fields