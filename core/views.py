from django.http import JsonResponse
from django.db import connection
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from accounts.message_usage import dashboard_stats_for_user
from core.activities import recent_activities_for_user
from core.sync_history import sync_history_item, sync_history_queryset
from rest_framework.pagination import PageNumberPagination

# --- 2. VIEWS DE API (BACKEND) ---

def health_check(request):
    """
    Verifica a saúde do serviço e a conectividade com o banco de dados.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
        return JsonResponse({"status": "error", "db_status": db_status}, status=500)

    return JsonResponse({
        "status": "ok",
        "db_status": db_status,
        "app_version": "v1.0.0"
    })


class DashboardStatsView(APIView):
    """
    GET /api/v1/dashboard/stats/
    Cards do dashboard: documentos analisados, automações rodadas, mensagens enviadas..
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(dashboard_stats_for_user(request.user))


class ActivitiesView(APIView):
    """
    GET /api/v1/activities/
    Feed de atividades recentes do dashboard.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(recent_activities_for_user(request.user))


class SyncHistoryPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class SyncHistoryView(APIView):
    """
    GET /api/v1/sync-history/?page=&page_size=
    Envios das automações para integrações externas (WhatsApp, webhook), sucesso e falha.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        paginator = SyncHistoryPagination()
        page = paginator.paginate_queryset(sync_history_queryset(request.user), request, view=self)
        return paginator.get_paginated_response([sync_history_item(log) for log in page])
