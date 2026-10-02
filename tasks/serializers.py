from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from accounts.models import OrganizationMembership
from accounts.team_roles import get_active_membership

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
    """
    POST /api/v1/tasks/ — formulário Criação Manual (NewTask).
    Campos: titulo, descricao, dataHorario, prioridade, responsavel, sincronizar.
    ``sincronizar`` é apenas persistido; sync Google/Outlook ainda não é executado.
    """

    dataHorario = serializers.DateTimeField(source='scheduled_at')
    prioridade = serializers.ChoiceField(
        source='priority',
        choices=UserTask.Priority.choices,
    )
    responsavel = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    sincronizar = serializers.BooleanField(required=False, default=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Antes qualquer utilizador autenticado podia atribuir tarefas a QUALQUER outro (IDOR
        # entre escritórios). Agora só ele próprio e membros ativos do mesmo escritório.
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            org_ids = user.memberships.filter(is_active=True).values_list('organization_id', flat=True)
            allowed = User.objects.filter(
                Q(pk=user.pk) | Q(memberships__organization_id__in=org_ids, memberships__is_active=True)
            ).distinct()
            self.fields['responsavel'].queryset = allowed

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None or not getattr(request.user, 'is_authenticated', False):
            self.fields['responsavel'].queryset = User.objects.none()
            return

        membership = get_active_membership(request.user)
        if membership is None:
            self.fields['responsavel'].queryset = User.objects.none()
            return

        user_ids = OrganizationMembership.objects.filter(
            organization=membership.organization,
            is_active=True,
        ).values_list('user_id', flat=True)
        self.fields['responsavel'].queryset = User.objects.filter(id__in=user_ids)


class UserTaskUpdateSerializer(serializers.ModelSerializer):
    """PATCH /api/v1/tasks/{id}/ — atualiza estado de conclusão."""

    class Meta:
        model = UserTask
        fields = ['completed']
