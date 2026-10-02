from rest_framework import serializers

from accounts.tenancy import resolve_request_tenant
from integrations.models import AppConnection
from integrations.ssrf import UnsafeURLError, validate_outbound_url

from .models import Action, Trigger, Workflow


class TriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trigger
        fields = ["id", "connection", "event_type", "payload_mapping", "webhook_token"]
        read_only_fields = ["webhook_token"]

    def validate_connection(self, connection: AppConnection):
        """A conexão tem de pertencer a um membro do mesmo escritório (evita IDOR de conexões)."""
        request = self.context.get("request")
        tenant = resolve_request_tenant(request) if request is not None else None
        if tenant is None or not tenant.members.filter(
            user_id=connection.user_id, is_active=True
        ).exists():
            raise serializers.ValidationError("Conexão inválida para este escritório.")
        return connection


class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action
        fields = ["id", "action_type", "endpoint_url", "method", "headers", "payload_template"]

    def validate_headers(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError("headers tem de ser um objeto JSON.")
        return value

    def validate(self, attrs):
        url = attrs.get("endpoint_url")
        if url:
            try:
                # Sintaxe/esquema/credenciais já no cadastro; a resolução DNS é revalidada no envio.
                validate_outbound_url(url, resolve=False)
            except UnsafeURLError as exc:
                raise serializers.ValidationError({"endpoint_url": str(exc)})
        return attrs


class WorkflowSerializer(serializers.ModelSerializer):
    # Permite ler e escrever o gatilho e as ações de forma aninhada
    trigger = TriggerSerializer()
    actions = ActionSerializer(many=True)

    class Meta:
        model = Workflow
        # ``organization`` NÃO entra nos fields: só via
        # TenantAwareViewSet.perform_create → serializer.save(organization=tenant)
        fields = ["id", "name", "description", "is_active", "trigger", "actions", "created_at",
                  "ai_generated", "approved_at", "awaiting_approval"]
        read_only_fields = ["created_at", "ai_generated", "approved_at", "awaiting_approval"]

    awaiting_approval = serializers.BooleanField(read_only=True)

    def validate(self, attrs):
        # RNE-016: rascunho de IA não pode ser ativado por PATCH; só pelo endpoint de aprovação.
        if self.instance is not None and self.instance.awaiting_approval and attrs.get("is_active"):
            raise serializers.ValidationError(
                {"is_active": "Workflow gerado por IA aguarda aprovação de um Administrador/Dono."}
            )
        return attrs

    def create(self, validated_data):
        trigger_data = validated_data.pop("trigger")
        actions_data = validated_data.pop("actions")

        # organization vem de perform_create (save(organization=tenant)); o cliente
        # não consegue forçar outro escritório porque o campo não é writável na API.
        workflow = Workflow.objects.create(**validated_data)
        Trigger.objects.create(workflow=workflow, **trigger_data)
        for action_data in actions_data:
            Action.objects.create(workflow=workflow, **action_data)
        return workflow

    def update(self, instance, validated_data):
        trigger_data = validated_data.pop("trigger", None)
        actions_data = validated_data.pop("actions", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if trigger_data is not None:
            for field, value in trigger_data.items():
                setattr(instance.trigger, field, value)
            instance.trigger.save()
        if actions_data is not None:
            instance.actions.all().delete()
            for action_data in actions_data:
                Action.objects.create(workflow=instance, **action_data)
        return instance
