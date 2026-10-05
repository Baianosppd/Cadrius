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
from backoffice import fiscal, services, staff
from backoffice.permissions import IsBackoffice, IsFiscal, IsTI, user_areas
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
        if 'fiscal' in areas:
            _, _, month = fiscal.payments_qs(None, None)
            data['fiscal'] = fiscal.summary(month)
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


# ----------------------------------------------------------------------------- equipe Cadrius (TI) — CAD-170
class StaffListView(APIView):
    """GET: equipe com áreas e MFA. POST {email, first_name, last_name, areas[], reason}: cria conta e envia o link de definir senha."""
    permission_classes = [IsTI]

    def get(self, request):
        User = get_user_model()
        qs = User.objects.filter(is_staff=True).order_by('-is_active', 'email')
        return Response([staff.staff_row(u) for u in qs])

    def post(self, request):
        reason = _reason(request)
        if reason is None:
            return Response({'detail': 'Informe o motivo (mínimo 10 caracteres): fica na trilha de auditoria.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            row = staff.create_staff(request.user, email=request.data.get('email'), first_name=request.data.get('first_name'),
                                     last_name=request.data.get('last_name'), areas=request.data.get('areas'), reason=reason)
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(row, status=status.HTTP_201_CREATED)


class StaffDetailView(APIView):
    """PATCH {areas[], reason}: muda as áreas; lista vazia tira a pessoa da equipe (e encerra as sessões)."""
    permission_classes = [IsTI]

    def patch(self, request, pk):
        user = get_user_model().objects.filter(pk=pk).first()
        if user is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        reason = _reason(request)
        if reason is None:
            return Response({'detail': 'Informe o motivo (mínimo 10 caracteres): fica na trilha de auditoria.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(staff.update_staff(request.user, user, areas=request.data.get('areas'), reason=reason))
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ----------------------------------------------------------------------------- setor Fiscal — CAD-170
class FiscalPaymentsView(APIView):
    """GET ?start=AAAA-MM-DD&end=AAAA-MM-DD&status=pending|issued|not_required — recebimentos do período e resumo."""
    permission_classes = [IsFiscal]

    def get(self, request):
        try:
            d0, d1, qs = fiscal.payments_qs(request.query_params.get('start'), request.query_params.get('end'),
                                            request.query_params.get('status'))
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        offset = max(int(request.query_params.get('offset') or 0), 0)
        return Response({'inicio': d0, 'fim': d1, 'resumo': fiscal.summary(qs),
                         'resultados': [fiscal.payment_row(p) for p in qs[offset:offset + PAGE]]})


class FiscalExportView(APIView):
    permission_classes = [IsFiscal]

    def get(self, request):
        from django.http import HttpResponse
        try:
            d0, d1, qs = fiscal.payments_qs(request.query_params.get('start'), request.query_params.get('end'),
                                            request.query_params.get('status'))
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        from audit import service as audit
        audit.log('data.export', actor=request.user, reason='recebimentos para o contador (Fiscal)',
                  changes={'inicio': str(d0), 'fim': str(d1), 'linhas': qs.count()}, data_categories=['financeiro', 'identificacao'],
                  legal_basis='obrigacao_legal')
        resp = HttpResponse('﻿' + fiscal.export_csv(qs), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="cadrius-recebimentos-{d0}-a-{d1}.csv"'
        return resp


class FiscalInvoiceView(APIView):
    """POST {status: issued|not_required|pending, number, issued_at, note, reason} — registra a NF emitida (fase 1: emissão fora)."""
    permission_classes = [IsFiscal]

    def post(self, request, pk):
        from billing.models import Payment
        payment = Payment.objects.select_related('organization').filter(pk=pk).first()
        if payment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        reason = _reason(request, minimum=5) or ''
        if not reason:
            return Response({'detail': 'Informe o motivo/observação (mínimo 5 caracteres).'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(fiscal.register_invoice(request.user, payment, status=str(request.data.get('status', '')),
                                                    number=request.data.get('number'), issued_at=request.data.get('issued_at'),
                                                    note=request.data.get('note'), reason=reason))
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ----------------------------------------------------------------------------- setor Fiscal — fases 2 e 3 (CAD-175)
class FiscalNfseView(APIView):
    """GET → conferência da nota (nada é enviado). POST {acao: emitir|atualizar|cancelar, reason/justificativa}."""
    permission_classes = [IsFiscal]

    def _payment(self, pk):
        from billing.models import Payment
        return Payment.objects.select_related('organization').filter(pk=pk).first()

    def get(self, request, pk):
        from backoffice import nfse
        payment = self._payment(pk)
        if payment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({**nfse.preview(payment), 'pagamento': nfse.row(payment)})

    def post(self, request, pk):
        from backoffice import nfse
        payment = self._payment(pk)
        if payment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        action = request.data.get('acao')
        try:
            if action == 'emitir':
                reason = _reason(request, minimum=5)
                if not reason:
                    return Response({'detail': 'Confirme a conferência com uma observação (mínimo 5 caracteres).'},
                                    status=status.HTTP_400_BAD_REQUEST)
                return Response(nfse.emit(request.user, payment, reason))
            if action == 'atualizar':
                return Response(nfse.refresh(payment))
            if action == 'cancelar':
                return Response(nfse.cancel(request.user, payment, str(request.data.get('justificativa', ''))))
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'detail': 'Ação inválida.'}, status=status.HTTP_400_BAD_REQUEST)


class FiscalObligationsView(APIView):
    """GET → próximos vencimentos (60 dias) + cadastro. PATCH {id, dia, mes, ajuste, ativa, reason} edita uma obrigação."""
    permission_classes = [IsFiscal]

    def get(self, request):
        from backoffice import nfse, obligations
        from billing.models import FiscalObligation
        return Response({'proximos': obligations.upcoming(), 'obrigacoes': [obligations.obligation_json(o) for o in FiscalObligation.objects.all()],
                         'emissor_automatico': nfse.is_automatic(), 'ajustes': FiscalObligation.Adjust.choices})

    def patch(self, request):
        from backoffice import obligations
        from billing.models import FiscalObligation
        ob = FiscalObligation.objects.filter(pk=request.data.get('id')).first()
        if ob is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        reason = _reason(request, minimum=5)
        if not reason:
            return Response({'detail': 'Informe o motivo da mudança (mínimo 5 caracteres).'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(obligations.update(request.user, ob, request.data, reason))
        except (services.ActionError, ValueError) as exc:
            return Response({'detail': str(exc) if isinstance(exc, services.ActionError) else 'Valor inválido.'},
                            status=status.HTTP_400_BAD_REQUEST)


class FiscalObligationDoneView(APIView):
    """POST {competencia, obs, desfazer} — marca (ou desmarca) a obrigação como cumprida naquela competência."""
    permission_classes = [IsFiscal]

    def post(self, request, pk):
        import re

        from backoffice import obligations
        from billing.models import FiscalObligation
        ob = FiscalObligation.objects.filter(pk=pk).first()
        if ob is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        comp = str(request.data.get('competencia', ''))
        if not re.fullmatch(r'\d{4}(-(0[1-9]|1[0-2]))?', comp) or (ob.periodicity == 'mensal') != ('-' in comp):
            return Response({'detail': 'Competência AAAA-MM (mensal) ou AAAA (anual).'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            obligations.mark_done(request.user, ob, comp, request.data.get('obs', ''), undo=bool(request.data.get('desfazer')))
        except services.ActionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'proximos': obligations.upcoming()})
