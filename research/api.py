"""API de pesquisa jurídica (CAD-166). Prefixo: /api/v1/research/"""
from __future__ import annotations

from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from audit import service as audit
from core.pii import blind_index
from research import cnj
from research.models import MonitoredCase, NewsItem
from research.monitor import check_case


def _membership(request):
    return get_active_membership(request.user)


class CaseSerializer(serializers.Serializer):
    cnj = serializers.CharField(max_length=40)
    label = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate_cnj(self, value):
        parsed = cnj.parse(value)
        if not parsed:
            raise serializers.ValidationError('Número CNJ inválido (confira os 20 dígitos).')
        if not cnj.tribunal_alias(parsed):
            raise serializers.ValidationError('Tribunal ainda não suportado pelo monitoramento.')
        return parsed


def _case_json(case, with_movements=False):
    data = {'id': case.pk, 'cnj': case.cnj, 'label': case.label, 'tribunal': case.tribunal, 'is_active': case.is_active,
            'last_checked_at': case.last_checked_at, 'last_movement_at': case.last_movement_at, 'last_error': case.last_error,
            'cliente': {'id': case.client_id, 'nome': case.client.name} if case.client_id else None}
    if with_movements:
        data['movements'] = [{'occurred_at': m.occurred_at, 'code': m.code, 'name': m.name, 'complement': m.complement}
                             for m in case.movements.all()[:100]]
    return data


def _client(organization, value):
    """Contato do quadro que é o cliente do processo (CAD-172: destinatário das automações). None desvincula."""
    from contacts.models import Contact

    if value in (None, ''):
        return None
    try:
        return Contact.objects.get(organization=organization, pk=int(value))
    except (ValueError, TypeError, Contact.DoesNotExist) as exc:
        raise serializers.ValidationError({'cliente_id': 'Contato não encontrado no escritório.'}) from exc


class CaseListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        membership = _membership(request)
        if membership is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        cases = MonitoredCase.objects.filter(organization=membership.organization).select_related('client')
        return Response([_case_json(c) for c in cases])

    def post(self, request):
        membership = _membership(request)
        if membership is None:
            return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        ser = CaseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        parsed = ser.validated_data['cnj']
        if MonitoredCase.objects.filter(organization=membership.organization,
                                        cnj_bidx=blind_index('case.cnj', parsed['digits'])).exists():
            return Response({'detail': 'Este processo já está sendo monitorado.'}, status=status.HTTP_409_CONFLICT)
        client = _client(membership.organization, request.data.get('cliente_id'))
        case = MonitoredCase.objects.create(organization=membership.organization, cnj=parsed['formatted'],
                                            tribunal=cnj.tribunal_alias(parsed), label=ser.validated_data.get('label', ''),
                                            responsavel=request.user, client=client)
        audit.log('research.case_added', actor=request.user, organization=membership.organization, target=case,
                  changes={'tribunal': case.tribunal}, data_categories=['dados_processuais'], legal_basis='exercicio_regular_direitos')
        return Response(_case_json(case), status=status.HTTP_201_CREATED)


class CaseDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get(self, request, pk):
        membership = _membership(request)
        if membership is None:
            return None
        return MonitoredCase.objects.filter(organization=membership.organization, pk=pk).first()

    def get(self, request, pk):
        case = self._get(request, pk)
        if case is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_case_json(case, with_movements=True))

    def patch(self, request, pk):
        """Apelido e cliente do processo. {label?, cliente_id?: id | null}"""
        case = self._get(request, pk)
        if case is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if _membership(request).role == 'VIEWER':
            return Response({'detail': 'Seu perfil é somente leitura.'}, status=status.HTTP_403_FORBIDDEN)
        if 'cliente_id' in request.data:
            case.client = _client(case.organization, request.data.get('cliente_id'))
        if 'label' in request.data:
            case.label = str(request.data.get('label') or '').strip()[:120]
        case.save(update_fields=['client', 'label'])
        return Response(_case_json(case))

    def delete(self, request, pk):
        case = self._get(request, pk)
        if case is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('research.case_removed', actor=request.user, organization=case.organization, target=case, changes={},
                  data_categories=['dados_processuais'], legal_basis='exercicio_regular_direitos')
        case.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CaseCheckNowView(CaseDetailView):
    def post(self, request, pk):
        case = self._get(request, pk)
        if case is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        result = check_case(case)
        return Response({**result, 'case': _case_json(case, with_movements=True)})


class NewsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response([{'source': n.source, 'url': n.url, 'title': n.title, 'summary': n.summary, 'published_at': n.published_at}
                         for n in NewsItem.objects.all()[:50]])
