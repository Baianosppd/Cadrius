from rest_framework import viewsets, mixins, status
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django_q.models import Schedule

from .models import MailBox, EmailMessage
from extraction.models import ExtractionProfile
from .serializers import (
    MailBoxSerializer, EmailMessageSerializer, ExtractionProfileSerializer
)

class MailBoxViewSet(viewsets.ModelViewSet):
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
    queryset = EmailMessage.objects.all()
    serializer_class = EmailMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return EmailMessage.objects.none()

        queryset = EmailMessage.objects.filter(mailbox__user=self.request.user).order_by('-received_at')
        search_query = self.request.query_params.get('q')

        if search_query:
            queryset = queryset.filter(
                Q(subject__icontains=search_query) | Q(sender__icontains=search_query)
            )
        return queryset

class ExtractionProfileViewSet(viewsets.ModelViewSet):
    queryset = ExtractionProfile.objects.all()
    serializer_class = ExtractionProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return ExtractionProfile.objects.none()
        return ExtractionProfile.objects.filter(user=self.request.user).order_by('name')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)