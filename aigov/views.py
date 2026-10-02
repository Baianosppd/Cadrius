from datetime import timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django_q.tasks import async_task

from accounts.permissions import IsOrgManager
from accounts.tenancy import resolve_request_tenant
from audit import service as audit
from aigov import drafts
from aigov.guard import AIBlocked, get_policy
from aigov.models import AIActionLog
from aigov.serializers import AIActionLogSerializer, PendingExecutionSerializer, PolicySerializer
from integrations.models import AppConnection
from workflows.models import ExecutionLog
from workflows.serializers import WorkflowSerializer
from workflows.services import generate_workflow_from_prompt


class PolicyView(APIView):
    """GET (qualquer membro) / PATCH (OWNER/ADMIN) /api/v1/ai/policy/ — governança de IA do escritório."""

    def get_permissions(self):
        from rest_framework.permissions import IsAuthenticated
        return [IsOrgManager()] if self.request.method == 'PATCH' else [IsAuthenticated()]

    def get(self, request):
        tenant = resolve_request_tenant(request)
        if tenant is None:
            return Response({'detail': 'Sem escritório ativo.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(PolicySerializer(get_policy(tenant)).data)

    def patch(self, request):
        tenant = resolve_request_tenant(request)
        policy = get_policy(tenant)
        before = PolicySerializer(policy).data
        serializer = PolicySerializer(policy, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=str(request.user.pk))
        audit.log('org.updated', actor=request.user, organization=tenant, target=policy,
                  changes={'ai_policy': sorted(serializer.validated_data),
                           'autonomy_from': before['autonomy_level'], 'autonomy_to': policy.autonomy_level})
        return Response(PolicySerializer(policy).data)


class ActivityView(APIView):
    """GET /api/v1/ai/activity/ — uso de IA do escritório (sem conteúdo) + resumo de 7 dias."""

    def get_permissions(self):
        return [IsOrgManager()]

    def get(self, request):
        tenant = resolve_request_tenant(request)
        logs = AIActionLog.objects.filter(organization_id=tenant.pk)
        week = logs.filter(created_at__gte=timezone.now() - timedelta(days=7))
        return Response({
            'summary': {
                'requests_7d': week.filter(blocked=False).count(),
                'blocked_7d': week.filter(blocked=True).count(),
                'failed_7d': week.filter(blocked=False, success=False).count(),
                'by_provider': dict(week.filter(blocked=False).values_list('provider').annotate(n=Count('id'))),
                'by_block_reason': dict(week.filter(blocked=True).values_list('block_reason').annotate(n=Count('id'))),
            },
            'recent': AIActionLogSerializer(logs[:50], many=True).data,
        })


class CreateAIWorkflowDraftView(APIView):
    """
    POST /api/v1/ai/workflows/ {prompt, connection_id} — a IA gera e o sistema grava como RASCUNHO inativo.
    A ativação exige POST /api/workflows/automations/<id>/approve/ por OWNER/ADMIN (RNE-016).
    """

    def post(self, request):
        from accounts.permissions import OrgRolePermission
        if not OrgRolePermission().has_permission(request, self):
            return Response({'detail': OrgRolePermission.message}, status=status.HTTP_403_FORBIDDEN)
        tenant = resolve_request_tenant(request)
        if tenant is None:
            return Response({'detail': 'Sem escritório ativo.', 'code': 'no_organization'}, status=status.HTTP_403_FORBIDDEN)

        prompt = request.data.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip():
            return Response({'detail': 'Informe "prompt" (texto).'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            connection = AppConnection.objects.get(pk=request.data.get('connection_id'))
        except (AppConnection.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'connection_id inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        if not tenant.members.filter(user_id=connection.user_id, is_active=True).exists():
            return Response({'detail': 'connection_id inválido.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            generated = generate_workflow_from_prompt(prompt.strip(), tenant, user=request.user)
        except AIBlocked as blocked:
            return Response({'detail': blocked.message, 'code': blocked.code}, status=status.HTTP_403_FORBIDDEN)
        if generated is None:
            return Response({'detail': 'A IA não conseguiu gerar um workflow válido.', 'code': 'workflow_generation_failed'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        from rest_framework.exceptions import ValidationError
        try:
            workflow = drafts.create_ai_draft(organization=tenant, user=request.user, connection=connection,
                                              generated=generated)
        except ValidationError as exc:
            return Response({'detail': exc.detail, 'code': 'invalid_ai_output'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        return Response(WorkflowSerializer(workflow, context={'request': request}).data, status=status.HTTP_201_CREATED)


class PendingExecutionsView(generics.ListAPIView):
    """GET /api/v1/ai/executions/pending/ — fila de execuções de origem IA aguardando confirmação humana."""

    permission_classes = [IsOrgManager]
    serializer_class = PendingExecutionSerializer
    pagination_class = None

    def get_queryset(self):
        tenant = resolve_request_tenant(self.request)
        return (ExecutionLog.objects.filter(workflow__organization=tenant, status='PENDING_REVIEW')
                .select_related('workflow').prefetch_related('workflow__actions').order_by('created_at'))


class ReviewExecutionView(APIView):
    """POST /api/v1/ai/executions/<id>/review/ {decision: approve|reject} — human-in-the-loop (RF-023)."""

    permission_classes = [IsOrgManager]

    def post(self, request, pk):
        tenant = resolve_request_tenant(request)
        try:
            log = ExecutionLog.objects.select_related('workflow').get(pk=pk, workflow__organization=tenant,
                                                                     status='PENDING_REVIEW')
        except ExecutionLog.DoesNotExist:
            return Response({'detail': 'Execução não encontrada ou já revista.'}, status=status.HTTP_404_NOT_FOUND)

        decision = request.data.get('decision')
        if decision not in ('approve', 'reject'):
            return Response({'detail': 'decision deve ser "approve" ou "reject".'}, status=status.HTTP_400_BAD_REQUEST)

        log.reviewed_by, log.reviewed_at = request.user, timezone.now()
        if decision == 'approve':
            log.review_decision, log.status = 'approved', 'PENDING'
            log.save(update_fields=['reviewed_by', 'reviewed_at', 'review_decision', 'status'])
            async_task('workflows.tasks.process_workflow_execution', log.pk)
        else:
            log.review_decision, log.status = 'rejected', 'FAILED'
            log.error_message = 'Rejeitada pelo revisor humano.'
            log.trigger_payload = None  # conteúdo descartado: a execução não vai acontecer
            log.save(update_fields=['reviewed_by', 'reviewed_at', 'review_decision', 'status', 'error_message',
                                    'trigger_payload'])
        audit.log('workflow.approved' if decision == 'approve' else 'ai.blocked', actor=request.user,
                  organization=tenant, target=log, reason=f'revisão humana: {decision}',
                  changes={'decision': decision})
        return Response({'id': log.pk, 'status': log.status, 'decision': log.review_decision})
