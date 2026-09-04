from rest_framework import serializers
from .models import Workflow, Trigger, Action

class TriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trigger
        fields = ["id", "connection", "event_type", "payload_mapping", "webhook_token"]
        read_only_fields = ["webhook_token"]

class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action
        fields = ['id', 'connection', 'action_type', 'order', 'payload_template']

class WorkflowSerializer(serializers.ModelSerializer):
    # Permite ler e escrever o gatilho e as ações de forma aninhada
    trigger = TriggerSerializer()
    actions = ActionSerializer(many=True)

    class Meta:
        model = Workflow
        # ``organization`` NÃO entra nos fields: só via
        # TenantAwareViewSet.perform_create → serializer.save(organization=tenant)
        fields = ['id', 'name', 'description', 'is_active', 'trigger', 'actions', 'created_at']
        read_only_fields = ['created_at']

    def create(self, validated_data):
        trigger_data = validated_data.pop('trigger')
        actions_data = validated_data.pop('actions')

        # organization vem de perform_create (save(organization=tenant)); o cliente
        # não consegue forçar outro escritório porque o campo não é writável na API.
        workflow = Workflow.objects.create(**validated_data)

        Trigger.objects.create(workflow=workflow, **trigger_data)

        for action_data in actions_data:
            Action.objects.create(workflow=workflow, **action_data)

        return workflow
