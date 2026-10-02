from rest_framework import mixins
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django_q.models import Schedule

from accounts.tenancy import TenantAwareGenericViewSet, TenantAwareViewSet
from accounts.permissions import OrgRolePermission
from audit import service
from audit.mixins import AuditedModelMixin

from .models import MailBox, EmailMessage
from extraction.models import ExtractionProfile
from .serializers import (
    MailBoxSerializer, EmailMessageSerializer, ExtractionProfileSerializer
)


class MailBoxViewSet(AuditedModelMixin, TenantAwareViewSet):
    """
    CRUD de caixas IMAP. Herda TenantAwareViewSet; o model ainda é por
    ``user`` (sem FK organization) — filtro/create sobrescritos em conformidade.
    """

    audit_prefix = "mailbox"
    audit_categories = ("credencial",)
    queryset = MailBox.objects.all()
    serializer_class = MailBoxSerializer
    permission_classes = [OrgRolePermission]
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
        # perform_create sobrescrito não passa pelo mixin: audita explicitamente.
        self._audit("created", mailbox, {"fields": sorted(serializer.validated_data)})

    def perform_destroy(self, instance):
        Schedule.objects.filter(
            func="tasks.tasks.fetch_emails",
            args=f"{instance.id}",
        ).delete()
        service.log("mailbox.deleted", target=instance, data_categories=self.audit_categories,
                    legal_basis="contrato")
        instance.delete()


class EmailMessageViewSet(
    AuditedModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    TenantAwareGenericViewSet,
):
    # Conteúdo de comunicações (dados de terceiros): leituras ficam na trilha (LGPD art. 37).
    audit_prefix = "email"
    audit_read_action = "data.read"
    audit_categories = ("contato", "conteudo_comunicacao", "processual")
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


class ExtractionProfileViewSet(AuditedModelMixin, TenantAwareViewSet):
    audit_prefix = "extractionprofile"
    queryset = ExtractionProfile.objects.all()
    serializer_class = ExtractionProfileSerializer
    permission_classes = [OrgRolePermission]
    require_tenant_on_create = False

    def filter_queryset_by_tenant(self, queryset):
        return queryset.filter(user=self.request.user).order_by("name")

    def get_perform_create_kwargs(self):
        return {"user": self.request.user}
