from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django_q.models import Schedule
from django_q.tasks import async_task

from .models import MailBox, EmailMessage, AutomationRule
from integrations.models import IntegrationConfig
from extraction.models import ExtractionProfile
from .serializers import (
    MailBoxSerializer, EmailMessageSerializer,
    IntegrationConfigSerializer, ExtractionProfileSerializer, AutomationRuleSerializer
)

class MailBoxViewSet(viewsets.ModelViewSet):
    """
    Endpoints: /api/v1/mailboxes/ - CRUD de caixas de e-mail (Filtrado por usuário).
    """
    queryset = MailBox.objects.all()
    serializer_class = MailBoxSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return MailBox.objects.none()
        if self.request.user.is_superuser:
            return MailBox.objects.all().order_by('name')
        return MailBox.objects.filter(user=self.request.user).order_by('name')

    def perform_create(self, serializer):
        mailbox = serializer.save(user=self.request.user)
        Schedule.objects.create(
            func='tasks.tasks.fetch_emails',
            args=f'{mailbox.id}',
            schedule_type=Schedule.MINUTES,
            minutes=5,
            name=f'Fetch - MailBox {mailbox.id} ({mailbox.name})',
        )

    def perform_destroy(self, instance):
        Schedule.objects.filter(
            func='tasks.tasks.fetch_emails',
            args=f'{instance.id}',
        ).delete()
        instance.delete()

class EmailMessageViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Endpoints: /api/v1/emails/ - Listagem, Detalhe e Reprocessamento de mensagens (Filtrado por usuário).
    """
    queryset = EmailMessage.objects.all()
    serializer_class = EmailMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return EmailMessage.objects.none()

        queryset = EmailMessage.objects.filter(mailbox__user=self.request.user).order_by('-received_at')
        status_filter = self.request.query_params.get('status')
        search_query = self.request.query_params.get('q')

        if status_filter:
            queryset = queryset.filter(status=status_filter.upper())
        if search_query:
            queryset = queryset.filter(
                Q(subject__icontains=search_query) | Q(sender__icontains=search_query)
            )
        return queryset

    @action(detail=True, methods=['post'], url_path='reprocess')
    def reprocess(self, request, pk=None):
        """
        Marca um email para ser re-processado (enfileira novamente a tarefa).
        """
        email = self.get_object()
        email.re_enqueue_for_processing()
        async_task('tasks.process_email', email.id)
        return Response({
            "detail": "Email enfileirado para reprocessamento.",
            "new_status": email.status_display
        }, status=status.HTTP_202_ACCEPTED)

class IntegrationConfigViewSet(viewsets.ModelViewSet):
    """
    Endpoints: /api/v1/integration-configs/ - CRUD de credenciais de integração.
    """
    queryset = IntegrationConfig.objects.all()
    serializer_class = IntegrationConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return IntegrationConfig.objects.none()
        return IntegrationConfig.objects.filter(user=self.request.user).order_by('name')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class ExtractionProfileViewSet(viewsets.ModelViewSet):
    """
    Endpoints: /api/v1/extraction-profiles/ - CRUD de perfis de IA (Prompt e Schema).
    """
    queryset = ExtractionProfile.objects.all()
    serializer_class = ExtractionProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return ExtractionProfile.objects.none()
        return ExtractionProfile.objects.filter(user=self.request.user).order_by('name')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class AutomationRuleViewSet(viewsets.ModelViewSet):
    """
    Endpoints: /api/v1/automation-rules/ - CRUD das regras de automação.
    """
    queryset = AutomationRule.objects.all()
    serializer_class = AutomationRuleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = AutomationRule.objects.filter(user=self.request.user).order_by('priority', 'name')
        if getattr(self, 'swagger_fake_view', False):
            return AutomationRule.objects.none()
        mailbox_id = self.request.query_params.get('mailbox_id')
        if mailbox_id:
            queryset = queryset.filter(mailbox__id=mailbox_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)