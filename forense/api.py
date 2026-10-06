"""API da agenda forense (CAD-172). Prefixo: /api/v1/forense/"""
from __future__ import annotations

from datetime import date

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from forense.calendar import Calendar
from forense.models import Holiday


class PrazoView(APIView):
    """GET ?inicio=AAAA-MM-DD&dias=15&tribunal=tjsp&disponibilizacao=1 → vencimento + dias pulados e motivos."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        m = get_active_membership(request.user)
        try:
            start = date.fromisoformat(request.query_params.get('inicio', ''))
            days = int(request.query_params.get('dias', ''))
            result = Calendar(m.organization if m else None, request.query_params.get('tribunal', '')).count(
                start, days, from_availability=request.query_params.get('disponibilizacao') == '1')
        except (TypeError, ValueError) as exc:
            msg = str(exc) if 'Prazo entre' in str(exc) else 'Informe a data (AAAA-MM-DD) e a quantidade de dias.'
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**result, 'aviso': 'Sugestão de prazo. Confira o calendário do tribunal (feriados locais e suspensões).'})


class HolidayListView(APIView):
    """Feriados do escritório (municipais, estaduais, do tribunal). Leitura: todos; cadastro: dono/admin."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        return Response([{'id': h.pk, 'data': h.date, 'nome': h.name, 'tribunal': h.tribunal, 'anual': h.yearly}
                         for h in Holiday.objects.filter(organization=m.organization)])

    def post(self, request):
        m = get_active_membership(request.user)
        if m is None or m.role not in MANAGE_TEAM_ROLES:
            return Response({'detail': 'Apenas dono/administrador cadastra feriados.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            day = date.fromisoformat(str(request.data.get('data', '')))
        except ValueError:
            return Response({'detail': 'Data no formato AAAA-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        name = str(request.data.get('nome', '')).strip()[:120]
        if len(name) < 3:
            return Response({'detail': 'Informe o nome do feriado.'}, status=status.HTTP_400_BAD_REQUEST)
        h = Holiday.objects.create(organization=m.organization, date=day, name=name,
                                   tribunal=str(request.data.get('tribunal', '')).strip().lower()[:12],
                                   yearly=bool(request.data.get('anual')))
        return Response({'id': h.pk, 'data': h.date, 'nome': h.name, 'tribunal': h.tribunal, 'anual': h.yearly}, status=status.HTTP_201_CREATED)


class HolidayDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        m = get_active_membership(request.user)
        if m is None or m.role not in MANAGE_TEAM_ROLES:
            return Response(status=status.HTTP_403_FORBIDDEN)
        deleted, _ = Holiday.objects.filter(organization=m.organization, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


# ----------------------------------------------------------------------------- calendário forense nacional (CAD-223)
class CourtSuspensionsView(APIView):
    """GET — suspensões de prazo/indisponibilidades que afetam os tribunais dos processos do escritório (e as nacionais)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from forense import courts
        m = get_active_membership(request.user)
        if m is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(courts.for_org(m.organization))


class CourtDirectoryView(APIView):
    """GET — dados de serviço dos tribunais (Balcão Virtual, serviços, pauta) mantidos pela Cadrius."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from forense import courts
        from forense.models import CourtInfo
        return Response([courts.info_json(c) for c in CourtInfo.objects.all()])


class StaffSuspensionsView(APIView):
    """Gestão Cadrius → Jurídico. GET lista; POST cadastra (avisa os escritórios afetados pelo gatilho court_suspension)."""

    def get_permissions(self):
        from backoffice.permissions import IsJuridico
        return [IsJuridico()]

    def get(self, request):
        from forense import courts
        from forense.models import CourtSuspension
        return Response([courts.suspension_json(s) for s in CourtSuspension.objects.all()[:300]])

    def post(self, request):
        from forense import courts
        try:
            s = courts.save_suspension(request.user, request.data)
        except courts.CourtError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({**courts.suspension_json(s), 'escritorios_avisados': courts.affected_orgs(s).count()},
                        status=status.HTTP_201_CREATED)


class StaffSuspensionDetailView(StaffSuspensionsView):
    def patch(self, request, pk):
        from forense import courts
        from forense.models import CourtSuspension
        s = CourtSuspension.objects.filter(pk=pk).first()
        if s is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            s = courts.save_suspension(request.user, request.data, s)
        except courts.CourtError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(courts.suspension_json(s))

    def delete(self, request, pk):
        from audit import service as audit
        from forense.models import CourtSuspension
        s = CourtSuspension.objects.filter(pk=pk).first()
        if s is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('forense.suspension_deleted', actor=request.user, target=s, changes={'tribunal': s.tribunal, 'inicio': s.start.isoformat()})
        s.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffCourtInfoView(APIView):
    def get_permissions(self):
        from backoffice.permissions import IsJuridico
        return [IsJuridico()]

    def get(self, request):
        from forense import courts
        from forense.models import CourtInfo
        return Response([courts.info_json(c) for c in CourtInfo.objects.all()])

    def post(self, request):
        from forense import courts
        try:
            c = courts.save_info(request.user, request.data)
        except courts.CourtError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(courts.info_json(c))
