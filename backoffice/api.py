"""API da Gestão Cadrius (CAD-168). Prefixo: /api/v1/backoffice/ — só equipe Cadrius, separada por área (TI / Financeiro)."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organization
from aigov.guard import set_global_switch
from backoffice import services
from backoffice.permissions import IsBackoffice, IsTI, user_areas
from billing import entitlements as ent
from core.pii import filter_by_term

PAGE = 50
STATES = ('trialing', 'active', 'past_due', 'restricted', 'suspended', 'canceled')
FINANCE_ACTIONS = {'extend_trial', 'grant_credits'}
TI_ACTIONS = {'deactivate', 'activate'}
USER_ACTIONS = {'unlock', 'deactivate', 'activate', 'revoke_sessions', 'send_password_reset', 'reset_mfa'}


def _reason(request, minimum=10):
    reason = str(request.data.get('reason', '')).strip()
    return reason if len(reason) >= minimum else None


class MeView(APIView):
    permission_classes = [IsBackoffice]

    def get(self, request):
        return Response({'areas': user_areas(request.user), 'email': request.user.email,
                         'superusuario': request.user.is_superuser})


class OverviewView(APIView):
    """Visão geral para as duas áreas; números financeiros só para quem é do Financeiro."""
    permission_classes = [IsBackoffice]

    def get(self, request):
        now = timezone.now()
        User = get_user_model()
        by_state = {s: 0 for s in STATES}
        for org in Organization.objects.select_related('plan').filter(is_active=True):
            by_state[ent.effective_status(org, now)] += 1
        data = {
            'escritorios': {'total': Organization.objects.count(), 'ativos': Organization.objects.filter(is_active=True).count(),
                            'novos_30d': Organization.objects.filter(created_at__gte=now - timedelta(days=30)).count(),
                            'por_estado': by_state},
            'usuarios': {'total': User.objects.filter(is_active=True).count(),
                         'acessaram_24h': User.objects.filter(last_login__gte=now - timedelta(hours=24)).count(),
                         'acessaram_30d': User.objects.filter(last_login__gte=now - timedelta(days=30)).count()},
        }
        areas = user_areas(request.user)
        if 'ti' in areas:
            q = services.queue_info()
            data['ti'] = {'falhas_fila_24h': q['falhas_24h'], 'fila': q['fila'], 'workers': q['workers']}
        if 'financeiro' in areas:
            from billing.admin_api import finance_summary
            data['financeiro'] = finance_summary()
        return Response(data)


class HealthView(APIView):
    permission_classes = [IsTI]

    def get(self, request):
        return Response(services.health())


class OrganizationListView(APIView):
    permission_classes = [IsBackoffice]

    def get(self, request):
        qs = Organization.objects.select_related('plan').annotate(
            n_members=Count('members', filter=Q(members__is_active=True))).order_by('-created_at')
        term = (request.query_params.get('q') or '').strip()
        if term:
            qs = qs.filter(Q(name__icontains=term) | Q(nome_fantasia__icontains=term))
        now = timezone.now()
        rows = [services.org_row(o, now) for o in qs]
        wanted = request.query_params.get('estado')
        if wanted in STATES:
            rows = [r for r in rows if r['estado'] == wanted]   # estado efetivo é calculado (datas), não coluna
        offset = max(int(request.query_params.get('offset') or 0), 0)
        return Response({'total': len(rows), 'resultados': rows[offset:offset + PAGE]})


class OrganizationDetailView(APIView):
    permission_classes = [IsBackoffice]

    def get(self, request, pk):
        org = Organization.objects.select_related('plan').filter(pk=pk).first()
        if org is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(services.org_detail(org))


class OrganizationActionView(APIView):
    """POST {action, reason, ...}. Financeiro: extend_trial{days}, grant_credits{credits, valid_days}. TI: deactivate, activate."""
    permission_classes = [IsBackoffice]

    def post(self, request, pk):
        org = Organization.objects.select_related('plan').filter(pk=pk).first()
        if org is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        action = str(request.data.get('action', ''))
        areas = user_areas(request.user)
        allowed = (FINANCE_ACTIONS if 'financeiro' in areas else set()) | (TI_ACTIONS if 'ti' in areas else set())
        if action not in FINANCE_ACTIONS | TI_ACTIONS:
            return Response({'detail': 'Ação desconhecida.'}, status=status.HTTP_400_BAD_REQUEST)
        if action not in allowed:
            return Response({'detail': 'Sua área não permite esta ação.'}, status=status.HTTP_403_FORBIDDEN)
        reason = _reason(request)
        if reason is None:
            return Response({'detail': 'Informe o motivo (mínimo 10 caracteres): fica na trilha de auditoria.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = services.org_action(request.user, org, action, request.data, reason)
        except (services.ActionError, ValueError) as exc:
            return Response({'detail': str(exc) if isinstance(exc, services.ActionError) else 'Valores inválidos.'},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class UserListView(APIView):
    permission_classes = [IsTI]

    def get(self, request):
        User = get_user_model()
        term = (request.query_params.get('q') or '').strip()
        qs = User.objects.prefetch_related('memberships__organization').order_by('-date_joined')
        if term:
            by_name = filter_by_term(User.objects.all(), 'name_idx', 'user.name', term).values('pk')
            qs = qs.filter(Q(email__icontains=term) | Q(pk__in=by_name))
        if request.query_params.get('equipe') == '1':
            qs = qs.filter(is_staff=True)
        offset = max(int(request.query_params.get('offset') or 0), 0)
        return Response({'total': qs.count(), 'resultados': [services.user_row(u) for u in qs[offset:offset + PAGE]]})


class UserActionView(APIView):
    permission_classes = [IsTI]

    def post(self, request, pk):
        user = get_user_model().objects.filter(pk=pk).first()
        if user is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        action = str(request.data.get('action', ''))
        if action not in USER_ACTIONS:
            return Response({'detail': 'Ação desconhecida.'}, status=status.HTTP_400_BAD_REQUEST)
        reason = _reason(request)
        if reason is None:
            return Response({'detail': 'Informe o motivo (mínimo 10 caracteres): fica na trilha de auditoria.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = services.user_action(request.user, user, action, reason)
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**result, 'usuario': services.user_row(user)})


class AISwitchView(APIView):
    """Kill switch GLOBAL da IA (todas as contas). Desligar exige motivo."""
    permission_classes = [IsTI]

    def post(self, request):
        enabled = request.data.get('enabled') is True
        reason = _reason(request) or ''
        if not enabled and not reason:
            return Response({'detail': 'Informe o motivo (mínimo 10 caracteres) para desligar a IA da plataforma.'},
                            status=status.HTTP_400_BAD_REQUEST)
        switch = set_global_switch(enabled, reason=reason, changed_by=str(request.user.pk))
        return Response({'ligada': switch.ai_enabled, 'motivo': switch.reason, 'alterado_em': switch.changed_at})
