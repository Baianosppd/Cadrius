import logging

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.db import connection
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from accounts.message_usage import dashboard_stats_for_user
from core.activities import recent_activities_for_user
from core.sync_history import sync_history_item, sync_history_queryset
from rest_framework.pagination import PageNumberPagination

logger = logging.getLogger(__name__)

# --- 2. VIEWS DE API (BACKEND) ---

def health_check(request):
    """
    Liveness + verificação do banco. Não devolve detalhes de erro (evita vazar
    informações internas a quem consulta o endpoint público).
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        logger.exception("healthz: falha ao consultar a base de dados")
        return JsonResponse({"status": "error", "db_status": "error"}, status=503)

    return JsonResponse({
        "status": "ok",
        "db_status": "ok",
        "app_version": getattr(settings, "APP_VERSION", "unknown"),
    })


def readiness_check(request):
    """
    Readiness: base de dados, cache/Redis (broker/sessões) e fila Django-Q.
    Pensado para o healthcheck do deploy/Traefik e para a tela de segurança.
    """
    checks = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        logger.exception("readyz: base de dados indisponível")
        checks["database"] = "error"

    try:
        cache.set("readyz", "1", timeout=5)
        checks["cache"] = "ok" if cache.get("readyz") == "1" else "error"
    except Exception:
        logger.exception("readyz: cache indisponível")
        checks["cache"] = "error"

    ready = all(v == "ok" for v in checks.values())
    return JsonResponse(
        {"status": "ok" if ready else "degraded", "checks": checks},
        status=200 if ready else 503,
    )


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
