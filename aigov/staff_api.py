"""Gestão Cadrius → IA por atividade (CAD-224). Área TI (consulta lê; total altera). Toda troca é auditada."""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from aigov import llm, routing
from aigov.models import AIRoute
from audit import service as audit
from backoffice.permissions import IsTI


def _providers():
    return [{'chave': p['chave'], 'nome': p['nome'], 'configurado': p['configurado'], 'modelo': p['modelo'],
             'treina_com_dados': p['treina_com_dados'], 'local': p['local'], 'gratuito': p['gratuito'],
             'saude': routing.health(p['chave'])} for p in llm.catalog()]


class RoutesView(APIView):
    permission_classes = [IsTI]

    def get(self, request):
        return Response({'atividades': routing.overview(), 'provedores': _providers(),
                         'regras': ['Se o provedor da vez falhar, o próximo da cadeia assume na mesma hora.',
                                    'Depois de 3 falhas seguidas o provedor vai para o fim da fila por 5 minutos (e volta sozinho).',
                                    'Dado de cliente nunca vai para provedor que treina com os dados, mesmo que esteja na cadeia.',
                                    'A chave própria de um escritório (Plugins) tem prioridade para aquele escritório.',
                                    'O escritório ainda decide quais provedores aceita (Segurança → IA segura).']})


class RouteDetailView(APIView):
    permission_classes = [IsTI]

    def patch(self, request, activity):
        if activity not in routing.ACTIVITIES:
            return Response({'detail': 'Atividade desconhecida.'}, status=status.HTTP_404_NOT_FOUND)
        providers = request.data.get('cadeia')
        if not isinstance(providers, list) or not providers or len(providers) > len(llm.PROVIDERS):
            return Response({'detail': 'Informe a cadeia com ao menos um provedor.'}, status=status.HTTP_400_BAD_REQUEST)
        clean = []
        for p in providers:
            key = str(p).upper()
            if key not in llm.PROVIDERS:
                return Response({'detail': f'Provedor desconhecido: {p}.'}, status=status.HTTP_400_BAD_REQUEST)
            if key not in clean:
                clean.append(key)
        if routing.ACTIVITIES[activity]['needs_tools'] and not any(llm.PROVIDERS[k].tools for k in clean):
            return Response({'detail': 'Esta atividade usa ferramentas: inclua um provedor que aceite ferramentas.'},
                            status=status.HTTP_400_BAD_REQUEST)
        before = routing.chain(activity)[0]
        route, _ = AIRoute.objects.update_or_create(activity=activity, defaults={
            'providers': clean, 'use_reserves': request.data.get('usar_reservas', True) is not False,
            'updated_by': request.user.email})
        routing.invalidate()
        audit.log('ai.route_changed', actor=request.user, target_type='ai_route', target_id=activity,
                  changes={'antes': before, 'depois': clean, 'reservas': route.use_reserves})
        return Response(next(a for a in routing.overview() if a['atividade'] == activity))

    def delete(self, request, activity):
        """Volta à recomendação do estudo."""
        if activity not in routing.ACTIVITIES:
            return Response({'detail': 'Atividade desconhecida.'}, status=status.HTTP_404_NOT_FOUND)
        AIRoute.objects.filter(activity=activity).delete()
        routing.invalidate()
        audit.log('ai.route_changed', actor=request.user, target_type='ai_route', target_id=activity, changes={'restaurado': True})
        return Response(next(a for a in routing.overview() if a['atividade'] == activity))
