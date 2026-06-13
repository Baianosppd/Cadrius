from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import UserTask

User = get_user_model()


class UserTaskListSerializer(serializers.ModelSerializer):
    description = serializers.CharField(source='titulo', read_only=True)
    time = serializers.SerializerMethodField()

    class Meta:
        model = UserTask
        fields = ['id', 'description', 'time', 'priority', 'completed']

    def get_time(self, obj):
        return timezone.localtime(obj.scheduled_at).strftime('%H:%M')


class UserTaskCreateSerializer(serializers.ModelSerializer):
    dataHorario = serializers.DateTimeField(source='scheduled_at')
    prioridade = serializers.ChoiceField(
        source='priority',
        choices=UserTask.Priority.choices,
    )
    responsavel = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    sincronizar = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = UserTask
        fields = [
            'titulo',
            'descricao',
            'dataHorario',
            'prioridade',
            'responsavel',
            'sincronizar',
        ]


class UserTaskUpdateSerializer(serializers.ModelSerializer):
    """PATCH /api/v1/tasks/{id}/ — atualiza estado de conclusão."""

    class Meta:
        model = UserTask
        fields = ['completed']
