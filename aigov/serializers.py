from rest_framework import serializers

from aigov.models import DEFAULT_PROVIDERS, AIActionLog, AIGovernancePolicy
from workflows.models import ExecutionLog


class PolicySerializer(serializers.ModelSerializer):
    requires_execution_review = serializers.SerializerMethodField()
    autonomy_choices = serializers.SerializerMethodField()

    class Meta:
        model = AIGovernancePolicy
        fields = ['ai_enabled', 'autonomy_level', 'allowed_providers', 'daily_ai_request_limit',
                  'max_actions_per_ai_workflow', 'updated_at', 'requires_execution_review', 'autonomy_choices']
        read_only_fields = ['updated_at', 'requires_execution_review', 'autonomy_choices']

    def get_requires_execution_review(self, obj) -> bool:
        return obj.requires_execution_review()

    def get_autonomy_choices(self, obj) -> list:
        return [{'value': v, 'label': l} for v, l in AIGovernancePolicy.Autonomy.choices]

    def validate_allowed_providers(self, value):
        invalid = [p for p in value if p not in DEFAULT_PROVIDERS]
        if invalid:
            raise serializers.ValidationError(f'Provedores inválidos: {", ".join(invalid)}.')
        return value

    def validate_daily_ai_request_limit(self, value):
        if value > 10_000:
            raise serializers.ValidationError('Máximo permitido: 10000 por dia.')
        return value


class AIActionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIActionLog
        fields = ['id', 'created_at', 'kind', 'provider', 'data_categories', 'input_chars', 'duration_ms',
                  'success', 'blocked', 'block_reason', 'request_id']
        read_only_fields = fields


class PendingExecutionSerializer(serializers.ModelSerializer):
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    action_summary = serializers.SerializerMethodField()
    # Pré-visualização do que será enviado: só nomes de campos do payload (nunca os valores).
    payload_fields = serializers.SerializerMethodField()

    class Meta:
        model = ExecutionLog
        fields = ['id', 'workflow', 'workflow_name', 'status', 'created_at', 'action_summary', 'payload_fields']
        read_only_fields = fields

    def get_action_summary(self, obj) -> list:
        return [{'type': a.action_type, 'target': a.endpoint_url or a.get_action_type_display()}
                for a in obj.workflow.actions.all()]

    def get_payload_fields(self, obj) -> list:
        payload = obj.trigger_payload
        return sorted(payload) if isinstance(payload, dict) else []
