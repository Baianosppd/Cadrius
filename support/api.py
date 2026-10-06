"""API do suporte (CAD-171). Cliente: /api/v1/support/ — Equipe (área Suporte ou TI): /api/v1/backoffice/support/."""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from backoffice.permissions import HasArea
from support import services
from support.models import Ticket

IsSupportStaff = HasArea.of('suporte', 'ti')
PAGE = 50


def _bad(exc):
    return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


# ----------------------------------------------------------------------------- cliente
class _Client(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def ticket(self, request, pk):
        m = get_active_membership(request.user)
        t = Ticket.objects.select_related('opened_by').filter(pk=pk).first()
        return (m, t) if t and services.can_see(m, t) else (m, None)


class TicketListView(_Client):
    def get(self, request):
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        qs = Ticket.objects.filter(organization=m.organization).select_related('opened_by')
        rows = [t for t in qs[:200] if services.can_see(m, t)]
        return Response([services.ticket_json(t) for t in rows])

    def post(self, request):
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            t = services.open_ticket(request.user, m.organization, subject=request.data.get('subject'),
                                     category=request.data.get('category'), priority=request.data.get('priority'),
                                     body=request.data.get('body'), page_url=request.data.get('page_url'))
        except ValueError as exc:
            return _bad(exc)
        return Response({**services.ticket_json(t), 'messages': services.messages_json(t)}, status=status.HTTP_201_CREATED)


class TicketDetailView(_Client):
    def get(self, request, pk):
        _, t = self.ticket(request, pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({**services.ticket_json(t), 'messages': services.messages_json(t)})


class TicketMessageView(_Client):
    def post(self, request, pk):
        _, t = self.ticket(request, pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            services.client_reply(request.user, t, request.data.get('body'))
        except ValueError as exc:
            return _bad(exc)
        return Response({**services.ticket_json(t), 'messages': services.messages_json(t)})


class TicketStatusView(_Client):
    """POST {action: close|reopen}."""

    def post(self, request, pk):
        _, t = self.ticket(request, pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        action = request.data.get('action')
        if action == 'close':
            services.set_status(t, Ticket.Status.CLOSED)
        elif action == 'reopen' and t.status in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
            services.set_status(t, Ticket.Status.OPEN)
        else:
            return _bad(ValueError('Ação inválida.'))
        return Response(services.ticket_json(t))


class TicketAccessView(_Client):
    """POST {hours: 24|72}: autoriza a equipe a ver os dados do escritório neste chamado. DELETE: revoga."""

    def post(self, request, pk):
        _, t = self.ticket(request, pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            services.grant_access(request.user, t, int(request.data.get('hours') or 0))
        except (TypeError, ValueError) as exc:
            return _bad(exc)
        return Response(services.ticket_json(t))

    def delete(self, request, pk):
        _, t = self.ticket(request, pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.revoke_access(request.user, t)
        return Response(services.ticket_json(t))


# ----------------------------------------------------------------------------- equipe Cadrius
class StaffTicketListView(APIView):
    permission_classes = [IsSupportStaff]

    def get(self, request):
        qs = Ticket.objects.select_related('organization', 'opened_by', 'assigned_to')
        st = request.query_params.get('status')
        if st == 'ativos':
            qs = qs.exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
        elif st in Ticket.Status.values:
            qs = qs.filter(status=st)
        if request.query_params.get('priority') in Ticket.Priority.values:
            qs = qs.filter(priority=request.query_params['priority'])
        if request.query_params.get('mine') == '1':
            qs = qs.filter(assigned_to=request.user)
        offset = max(int(request.query_params.get('offset') or 0), 0)
        return Response({'metricas': services.metrics(), 'total': qs.count(),
                         'resultados': [services.ticket_json(t, staff=True) for t in qs[offset:offset + PAGE]]})


class StaffTicketDetailView(APIView):
    """GET: chamado com notas internas. PATCH {status, priority, assign: 'me'|'none'}. POST {body, internal}: responder."""
    permission_classes = [IsSupportStaff]

    def _get(self, pk):
        return Ticket.objects.select_related('organization', 'opened_by', 'assigned_to').filter(pk=pk).first()

    def get(self, request, pk):
        t = self._get(pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({**services.ticket_json(t, staff=True), 'messages': services.messages_json(t, staff=True)})

    def patch(self, request, pk):
        t = self._get(pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            if 'status' in request.data:
                services.set_status(t, request.data['status'])
            if 'priority' in request.data:
                if request.data['priority'] not in Ticket.Priority.values:
                    raise ValueError('Prioridade inválida.')
                t.priority = request.data['priority']
                t.save(update_fields=['priority', 'updated_at'])
            if request.data.get('assign') in ('me', 'none'):
                t.assigned_to = request.user if request.data['assign'] == 'me' else None
                t.save(update_fields=['assigned_to', 'updated_at'])
        except ValueError as exc:
            return _bad(exc)
        return Response(services.ticket_json(t, staff=True))

    def post(self, request, pk):
        t = self._get(pk)
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            services.staff_reply(request.user, t, request.data.get('body'), internal=request.data.get('internal') is True)
        except ValueError as exc:
            return _bad(exc)
        return Response({**services.ticket_json(t, staff=True), 'messages': services.messages_json(t, staff=True)})


# ----------------------------------------------------------------------------- pedidos de parametrização (CAD-223)
class CustomizationListView(_Client):
    """GET: pedidos do escritório (+ áreas e dicas). POST: novo pedido (abre um chamado vinculado)."""

    def get(self, request):
        from support import customization as cz
        from support.models import CustomizationRequest
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        qs = CustomizationRequest.objects.filter(ticket__organization=m.organization).select_related('ticket').order_by('-created_at')
        rows = [r for r in qs[:100] if services.can_see(m, r.ticket)]
        return Response({'resultados': [cz.request_json(r) for r in rows],
                         'areas': [{'chave': k, 'rotulo': v, 'dica': cz.HINTS.get(k, '')} for k, v in CustomizationRequest.Area.choices]})

    def post(self, request):
        from support import customization as cz
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            r = cz.create(request.user, m, request.data)
        except ValueError as exc:
            return _bad(exc)
        return Response(cz.request_json(r), status=status.HTTP_201_CREATED)


class CustomizationDecisionView(_Client):
    def post(self, request, pk, decision):
        from support import customization as cz
        from support.models import CustomizationRequest
        m = get_active_membership(request.user)
        r = CustomizationRequest.objects.filter(pk=pk).select_related('ticket').first()
        if r is None or not services.can_see(m, r.ticket):
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            r = cz.client_decide(request.user, m, r, decision)
        except PermissionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return _bad(exc)
        return Response(cz.request_json(r))


class StaffCustomizationListView(APIView):
    permission_classes = [IsSupportStaff]

    def get(self, request):
        from support import customization as cz
        from support.models import CustomizationRequest
        qs = CustomizationRequest.objects.select_related('ticket', 'ticket__organization').order_by('-updated_at')
        if request.query_params.get('etapa') in CustomizationRequest.Stage.values:
            qs = qs.filter(stage=request.query_params['etapa'])
        counts = {s: CustomizationRequest.objects.filter(stage=s).count() for s in CustomizationRequest.Stage.values}
        return Response({'por_etapa': counts, 'resultados': [cz.request_json(r, staff=True) for r in qs[:PAGE]]})


class StaffCustomizationDetailView(APIView):
    permission_classes = [IsSupportStaff]

    def patch(self, request, pk):
        from support import customization as cz
        from support.models import CustomizationRequest
        r = CustomizationRequest.objects.filter(pk=pk).select_related('ticket', 'ticket__organization').first()
        if r is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            r = cz.staff_update(request.user, r, request.data)
        except ValueError as exc:
            return _bad(exc)
        return Response(cz.request_json(r, staff=True))
