from rest_framework import serializers

from audit.models import AnomalyAlert, AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            'seq', 'uid', 'occurred_at', 'request_id', 'actor_type', 'actor_id', 'actor_label',
            'action', 'target_type', 'target_id', 'outcome', 'reason', 'ip', 'auth_method',
            'changes', 'data_categories', 'legal_basis', 'hash',
        ]
        read_only_fields = fields


class AnomalyAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnomalyAlert
        fields = [
            'id', 'created_at', 'rule', 'severity', 'status', 'actor_id', 'actor_label', 'ip',
            'summary', 'details', 'reviewed_by', 'reviewed_at',
        ]
        read_only_fields = [f for f in fields if f != 'status']
