from rest_framework import mixins
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django_q.models import Schedule

from accounts.tenancy import TenantAwareGenericViewSet, TenantAwareViewSet

from .models import MailBox, EmailMessage
from extraction.models import ExtractionProfile
from .serializers import (
    MailBoxSerializer, EmailMessageSerializer, ExtractionProfileSerializer
)


class MailBoxViewSet(TenantAwareViewSet):
    """
    CRUD de caixas IMAP. Herda TenantAwareViewSet; o model ainda é por
    ``user`` (sem FK organization) — filtro/create sobrescritos em conformidade.
    """

    queryset = MailBox.objects.all()
    serializer_class = MailBoxSerializer
    permission_classes = [IsAuthenticated]
    require_tenant_on_create = False

    def filter_queryset_by_tenant(self, queryset):
        if self.request.user.is_superuser:
            return queryset.order_by("name")
        return queryset.filter(user=self.request.user).order_by("name")

    def perform_create(self, serializer):
        mailbox = serializer.save(user=self.request.user)
        Schedule.objects.create(
            func="tasks.tasks.fetch_emails",
            args=f"{mailbox.id}",
            schedule_type=Schedule.MINUTES,
            minutes=5,
            name=f"Fetch - MailBox {mailbox.id} ({mailbox.name})",
        )

    def perform_destroy(self, instance):
        Schedule.objects.filter(
            func="tasks.tasks.fetch_emails",
            args=f"{instance.id}",
        ).delete()
        instance.delete()


class EmailMessageViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    TenantAwareGenericViewSet,
):
    queryset = EmailMessage.objects.all()
    serializer_class = EmailMessageSerializer
    permission_classes = [IsAuthenticated]
    require_tenant_on_create = False

    def filter_queryset_by_tenant(self, queryset):
        queryset = queryset.filter(mailbox__user=self.request.user).order_by(
            "-received_at"
        )
        search_query = self.request.query_params.get("q")
        if search_query:
            queryset = queryset.filter(
                Q(subject__icontains=search_query) | Q(sender__icontains=search_query)
            )
        return queryset


class ExtractionProfileViewSet(TenantAwareViewSet):
    queryset = ExtractionProfile.objects.all()
    serializer_class = ExtractionProfileSerializer
    permission_classes = [IsAuthenticated]
    require_tenant_on_create = False

    def filter_queryset_by_tenant(self, queryset):
        return queryset.filter(user=self.request.user).order_by("name")

    def get_perform_create_kwargs(self):
        return {"user": self.request.user}
