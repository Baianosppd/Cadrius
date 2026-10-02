from rest_framework import serializers

from core.activities import format_relative_time

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    time = serializers.SerializerMethodField()
    read = serializers.SerializerMethodField()
    actionLabel = serializers.CharField(source="action_label", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "description",
            "time",
            "read",
            "type",
            "origem",
            "documento",
            "acao",
            "detalhes",
            "actionLabel",
            "link",
            "created_at",
        ]
        read_only_fields = fields

    def get_time(self, obj):
        return format_relative_time(obj.created_at)

    def get_read(self, obj):
        return obj.read_at is not None
