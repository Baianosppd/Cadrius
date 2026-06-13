from django.http import JsonResponse
from django.db import connection
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from accounts.message_usage import dashboard_stats_for_user
from core.activities import recent_activities_for_user

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
