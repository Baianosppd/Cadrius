from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Workflow
from .serializers import WorkflowSerializer


class WorkflowViewSet(viewsets.ModelViewSet):
    """
    CRUD de automações: workflow + gatilho (uma conexão de entrada) + passos (outras conexões).
    """
    serializer_class = WorkflowSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Workflow.objects.none()
        qs = Workflow.objects.select_related('trigger', 'user').prefetch_related('actions')
        user = self.request.user
        if user.is_superuser:
            return qs.order_by('-created_at')
        return qs.filter(user=user).order_by('-created_at')
