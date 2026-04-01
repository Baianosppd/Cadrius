from rest_framework import serializers

from integrations.models import AppConnection
from .models import Action, Trigger, Workflow


def _app_connection_queryset_for_request(request):
    if not request or not request.user.is_authenticated:
        return AppConnection.objects.none()
    if request.user.is_superuser:
        return AppConnection.objects.all()
    return AppConnection.objects.filter(user=request.user)


class TriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trigger
        fields = ['id', 'trigger_type', 'app_connection', 'payload_template']
        read_only_fields = ['id']


class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action
        fields = ['id', 'order', 'action_type', 'app_connection', 'payload_template']
        read_only_fields = ['id']


class WorkflowSerializer(serializers.ModelSerializer):
    trigger = TriggerSerializer(required=False)
    actions = ActionSerializer(many=True, required=False)

    class Meta:
        model = Workflow
        fields = [
            'id', 'name', 'description', 'is_active',
            'trigger', 'actions',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        qs = _app_connection_queryset_for_request(request)
        self.fields['trigger'].fields['app_connection'].queryset = qs
        self.fields['actions'].child.fields['app_connection'].queryset = qs

    def validate(self, attrs):
        request = self.context.get('request')
        if self.instance is None:
            if 'trigger' not in self.initial_data or 'actions' not in self.initial_data:
                raise serializers.ValidationError(
                    'Na criação, envie "trigger" e "actions".'
                )

        if not request or not request.user.is_authenticated:
            return attrs

        def check_conn(pk_or_obj):
            if pk_or_obj is None:
                return
            pk = getattr(pk_or_obj, 'pk', pk_or_obj)
            qs = _app_connection_queryset_for_request(request)
            if not qs.filter(pk=pk).exists():
                raise serializers.ValidationError(
                    'Conexão inválida ou não pertence ao usuário.'
                )

        trigger = attrs.get('trigger')
        if isinstance(trigger, dict):
            check_conn(trigger.get('app_connection'))

        actions = attrs.get('actions')
        if isinstance(actions, list):
            for item in actions:
                if isinstance(item, dict):
                    check_conn(item.get('app_connection'))

        return attrs

    def create(self, validated_data):
        trigger_data = validated_data.pop('trigger')
        actions_data = validated_data.pop('actions')
        user = self.context['request'].user
        workflow = Workflow.objects.create(user=user, **validated_data)
        Trigger.objects.create(workflow=workflow, **trigger_data)
        for action_data in actions_data:
            Action.objects.create(workflow=workflow, **action_data)
        return workflow

    def update(self, instance, validated_data):
        trigger_data = validated_data.pop('trigger', None)
        actions_data = validated_data.pop('actions', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if trigger_data is not None:
            try:
                trigger = instance.trigger
            except Trigger.DoesNotExist:
                Trigger.objects.create(workflow=instance, **trigger_data)
            else:
                for attr, value in trigger_data.items():
                    setattr(trigger, attr, value)
                trigger.save()

        if actions_data is not None:
            instance.actions.all().delete()
            for action_data in actions_data:
                Action.objects.create(workflow=instance, **action_data)

        return instance
