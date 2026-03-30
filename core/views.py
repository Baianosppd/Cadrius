from django.http import JsonResponse
from django.db import connection
from rest_framework.views import APIView 
from rest_framework.response import Response 
from rest_framework.permissions import IsAuthenticated 
from django.utils import timezone

# Importamos apenas o que sobrou no app emails
from emails.models import EmailMessage

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
    Retorna contagens e estatísticas para o Dashboard.
    [MODO MOCK]: Retornando dados zerados temporariamente após a refatoração
    arquitetural. A lógica real será reescrita na Sprint de Dashboards usando 
    o novo app 'workflows'.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        # Filtro seguro apenas para não dar erro, contando apenas emails da base
        today = timezone.now().date()
        if user.is_superuser:
            emails_today = EmailMessage.objects.filter(created_at__date=today).count()
        else:
            emails_today = EmailMessage.objects.filter(mailbox__user=user, created_at__date=today).count()

        # Retornamos a estrutura exata que o Front-end espera, mas com valores neutros
        return Response({
            "automacoes_ativas": 0, 
            "processos_ativos": 0,
            "prazos_hoje": emails_today,
            "tempo_economizado": "0h" 
        })