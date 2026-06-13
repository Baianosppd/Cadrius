from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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
    viewsets.GenericViewSet,
):
    """
    GET /api/v1/tasks/ — tarefas do dia do utilizador autenticado (responsável).
    POST /api/v1/tasks/ — cria tarefa a partir do formulário NewTask.jsx.
    PATCH /api/v1/tasks/{id}/ — marca tarefa como concluída ou pendente.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = None
    queryset = UserTask.objects.all()
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'create':
            return UserTaskCreateSerializer
        if self.action in ('update', 'partial_update'):
            return UserTaskUpdateSerializer
        return UserTaskListSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return UserTask.objects.none()

        today = timezone.localdate()
        return (
            UserTask.objects.filter(
                responsavel=self.request.user,
                scheduled_at__date=today,
            )
            .order_by('scheduled_at')
        )

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
