from rest_framework import serializers
from emails.models import MailBox, EmailMessage, EmailStatus, AutomationRule # NOVO: AutomationRule
from integrations.models import IntegrationLog, IntegrationConfig # NOVO: IntegrationConfig
from extraction.models import ExtractionProfile
from django.contrib.auth import get_user_model

# --- Serializers de MailBox (Jullio) ---

class MailBoxSerializer(serializers.ModelSerializer):
    """
    Serializer para o CRUD de MailBox.
    """
    # NOVO: Adiciona campos de FK customizados para visualização
    integration_config_name = serializers.CharField(source='integration_config.name', read_only=True)
    extraction_profile_name = serializers.CharField(source='extraction_profile.name', read_only=True)
    
    class Meta:
        model = MailBox
        fields = ['id', 'name', 'imap_host', 'imap_port', 'username', 'is_active', 'last_fetch_at', 
                  'integration_config', 'extraction_profile', 'integration_config_name', 'extraction_profile_name', 'user']
        read_only_fields = ['last_fetch_at', 'user', 'integration_config_name', 'extraction_profile_name']
        extra_kwargs = {
            'password': {'write_only': True}
        }

# --- Serializers de Configuração (NOVO) ---

class IntegrationConfigSerializer(serializers.ModelSerializer):
    """
    Serializer para o CRUD de IntegrationConfig (Trello/Telegram keys).
    """
    class Meta:
        model = IntegrationConfig
        # user é read_only e setado no ViewSet
        fields = ['id', 'name', 'trello_api_key', 'trello_api_token', 'trello_list_id', 
                  'telegram_bot_token', 'telegram_chat_id', 'is_active', 'user']
        read_only_fields = ['user']
        extra_kwargs = {
            # Credenciais são de escrita apenas, por segurança
            'trello_api_token': {'write_only': True},
            'telegram_bot_token': {'write_only': True},
        }

class ExtractionProfileSerializer(serializers.ModelSerializer):
    """
    Serializer para o CRUD de ExtractionProfile (Prompt + Schema Pydantic).
    """
    class Meta:
        model = ExtractionProfile
        fields = ['id', 'name', 'system_prompt_template', 'pydantic_schema_name', 'user']
        read_only_fields = ['user']

class AutomationRuleSerializer(serializers.ModelSerializer):
    """
    Serializer para o CRUD de AutomationRule (Regras de automação).
    """
    # Para melhor visualização dos FKs
    mailbox_name = serializers.CharField(source='mailbox.name', read_only=True)
    extraction_profile_name = serializers.CharField(source='extraction_profile.name', read_only=True)

    class Meta:
        model = AutomationRule
        fields = ['id', 'name', 'mailbox', 'mailbox_name', 'priority', 'is_active', 
                  'subject_contains', 'sender_contains', 'extraction_profile', 'extraction_profile_name', 
                  'action_config', 'user']
        read_only_fields = ['user', 'mailbox_name', 'extraction_profile_name']

class IntegrationLogSerializer(serializers.ModelSerializer):
    """
    Retorna os logs de integração (Trello/Telegram).
    """
    service_display = serializers.CharField(source='get_service_display', read_only=True)
    
    class Meta:
        model = IntegrationLog
        fields = ['id', 'service_display', 'status', 'response_code', 'attempted_at']
        read_only_fields = fields


class EmailMessageSerializer(serializers.ModelSerializer):
    """
    Serializer principal para listar e detalhar emails.
    Inclui os dados extraídos (Juliano) e os logs de integração (Thales).
    """
    mailbox_name = serializers.CharField(source='mailbox.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    # Rastreamento: Inclui logs de integração aninhados
    integration_logs = IntegrationLogSerializer(many=True, read_only=True)

    integration_logs_ext = IntegrationLogSerializer(
            source='integration_logs_ext', 
            many=True, 
            read_only=True
        )

    class Meta:
            model = EmailMessage
            # Note que 'body_text' pode ser grande, restrinja em list views se necessário.
            fields = [
                'id', 'mailbox_name', 'subject', 'sender', 'received_at', 
                'status', 'status_display', 'processing_attempts', 'last_processed_at',
                'body_text', 'extracted_data', 'integration_logs_ext' # <--- CAMPO ATUALIZADO
            ]
            read_only_fields = fields
            