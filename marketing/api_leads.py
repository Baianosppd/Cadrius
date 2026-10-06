"""Captação, resultados por canal e pesquisa de satisfação (CAD-223).

Escritório: /api/v1/marketing/formularios/… e /resultados/ (ler: módulo Marketing; criar/editar: "marketing.editar";
o formulário só fica público se ativo). Público: /api/v1/publico/captacao/<token>/ e /api/v1/publico/pesquisa/<token>/ — sem login,
com limite por IP e armadilha para robôs.
"""
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from accounts import access
from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from marketing import leads
from marketing.models import CaptureForm, SatisfactionSurvey

WRITE_ROLES = MANAGE_TEAM_ROLES | {'MEMBER'}


def _bad(msg, code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': msg}, status=code)


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def member(self, request, write=False):
        m = get_active_membership(request.user)
        if m is None:
            return None, _bad('Usuário sem escritório.', status.HTTP_403_FORBIDDEN)
        if write and not access.allowed(m, 'marketing.editar', WRITE_ROLES):
            return None, _bad('Seu perfil não permite esta ação.', status.HTTP_403_FORBIDDEN)
        return m, None


class FormListView(_Base):
    def get(self, request):
        m, err = self.member(request)
        if err:
            return err
        return Response([leads.form_json(f) for f in CaptureForm.objects.filter(organization=m.organization)])

    def post(self, request):
        m, err = self.member(request, write=True)
        if err:
            return err
        try:
            f = leads.save_form(m.organization, request.user, request.data)
        except leads.LeadError as exc:
            return _bad(str(exc))
        return Response(leads.form_json(f), status=status.HTTP_201_CREATED)


class FormDetailView(_Base):
    def patch(self, request, pk):
        m, err = self.member(request, write=True)
        if err:
            return err
        f = CaptureForm.objects.filter(organization=m.organization, pk=pk).first()
        if f is None:
            return _bad('Formulário não encontrado.', status.HTTP_404_NOT_FOUND)
        try:
            f = leads.save_form(m.organization, request.user, request.data, f)
        except leads.LeadError as exc:
            return _bad(str(exc))
        return Response(leads.form_json(f))

    def delete(self, request, pk):
        m, err = self.member(request, write=True)
        if err:
            return err
        deleted, _ = CaptureForm.objects.filter(organization=m.organization, pk=pk).delete()   # contatos e oportunidades ficam
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


class ResultsView(_Base):
    def get(self, request):
        m, err = self.member(request)
        if err:
            return err
        try:
            days = max(30, min(int(request.query_params.get('dias') or 180), 730))
        except ValueError:
            days = 180
        return Response(leads.channel_results(m.organization, days))


class PublicThrottle(AnonRateThrottle):
    scope = 'public_form'
    rate = '20/hour'

    def allow_request(self, request, view):
        if request.method == 'GET':
            return True                                   # só envios contam no limite
        return super().allow_request(request, view)


class PublicFormView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PublicThrottle]

    def form(self, token):
        if not 10 <= len(token or '') <= 60:
            return None
        return CaptureForm.objects.filter(token=token, active=True, organization__is_active=True).select_related('organization').first()

    def get(self, request, token):
        f = self.form(token)
        if f is None:
            return _bad('Formulário indisponível.', status.HTTP_404_NOT_FOUND)
        return Response(leads.public_json(f))

    def post(self, request, token):
        f = self.form(token)
        if f is None:
            return _bad('Formulário indisponível.', status.HTTP_404_NOT_FOUND)
        try:
            return Response({'mensagem': leads.submit(f, request.data)}, status=status.HTTP_201_CREATED)
        except leads.LeadError as exc:
            return _bad(str(exc))


class PublicSurveyView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PublicThrottle]

    def survey(self, token):
        if not 10 <= len(token or '') <= 60:
            return None
        return SatisfactionSurvey.objects.filter(token=token, organization__is_active=True).select_related('organization').first()

    def get(self, request, token):
        s = self.survey(token)
        if s is None or s.expires_at <= timezone.now():
            return _bad('Pesquisa indisponível.', status.HTTP_404_NOT_FOUND)
        return Response({'escritorio': s.organization.name, 'respondida': bool(s.answered_at),
                         'pergunta': f'De 0 a 10, quanto você recomendaria {s.organization.name} a um amigo ou familiar?'})

    def post(self, request, token):
        s = self.survey(token)
        if s is None:
            return _bad('Pesquisa indisponível.', status.HTTP_404_NOT_FOUND)
        try:
            leads.answer(s, request.data.get('nota'), request.data.get('comentario', ''))
        except leads.LeadError as exc:
            return _bad(str(exc))
        return Response({'mensagem': 'Obrigado pela sua avaliação!'})
