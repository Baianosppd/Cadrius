from django.utils import timezone
from rest_framework import mixins
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.tenancy import TenantAwareGenericViewSet

from .models import UserTask
from .serializers import (
    UserTaskCreateSerializer,
    UserTaskListSerializer,
    UserTaskUpdateSerializer,
)


class UserTaskViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    TenantAwareGenericViewSet,
):
    """
    GET /api/v1/tasks/ — tarefas do dia do utilizador autenticado (responsável).
    POST /api/v1/tasks/ — cria tarefa a partir do formulário NewTask.jsx.
    PATCH /api/v1/tasks/{id}/ — marca tarefa como concluída ou pendente.

    Isolamento por responsável (UserTask sem FK organization); herda a base
    tenant-aware para manter o padrão CAD-061 nos ViewSets.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = None
    queryset = UserTask.objects.all()
    http_method_names = ["get", "post", "patch", "head", "options"]
    require_tenant_on_create = False

    def get_serializer_class(self):
        if self.action == "create":
            return UserTaskCreateSerializer
        if self.action in ("update", "partial_update"):
            return UserTaskUpdateSerializer
        return UserTaskListSerializer

    def filter_queryset_by_tenant(self, queryset):
        today = timezone.localdate()
        return queryset.filter(
            responsavel=self.request.user,
            scheduled_at__date=today,
        ).order_by("scheduled_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        return Response(
            UserTaskListSerializer(task).data,
            status=201,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(UserTaskListSerializer(instance).data)
