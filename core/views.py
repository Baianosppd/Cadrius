from django.http import JsonResponse
from django.db import connection
from django.shortcuts import render, redirect
from rest_framework.views import APIView 
from rest_framework.response import Response 
from rest_framework import status 
from rest_framework.permissions import AllowAny, IsAuthenticated 

from emails.models import EmailMessage, AutomationRule, EmailStatus
from django.utils import timezone

# --- 1. VIEWS DE NAVEGAÇÃO (FRONTEND) ---

def login_view(request):
    """
    Renderiza a tela de login (login.html).
    Rota: /
    """
    # Se o usuário já estiver autenticado (via sessão do Django Admin ou similar),
    # podemos redirecionar, mas como usamos JWT no front, apenas servimos o HTML.
    return render(request, 'login.html')

def register_view(request):
    """
    Renderiza a tela de cadastro (register.html).
    Rota: /register/
    """
    return render(request, 'register.html')

def dashboard_view(request):
    """
    Renderiza o painel principal (dashboard.html).
    Rota: /dashboard/
    """
    return render(request, 'dashboard.html')

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
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        # Filtros baseados no usuário (Multi-tenancy)
        if user.is_superuser:
            automations_qs = AutomationRule.objects.all()
            emails_qs = EmailMessage.objects.all()
        else:
            automations_qs = AutomationRule.objects.filter(user=user)
            # emails via mailbox do usuário
            emails_qs = EmailMessage.objects.filter(mailbox__user=user)

        # 1. Automações Ativas
        active_automations = automations_qs.filter(is_active=True).count()

        # 2. Processos Ativos (Emails Extraídos com Sucesso)
        active_processes = emails_qs.filter(status=EmailStatus.EXTRACTED).count()

        # 3. Emails processados hoje (Simulação de 'Prazos Hoje')
        today = timezone.now().date()
        emails_today = emails_qs.filter(received_at__date=today).count()

        return Response({
            "automacoes_ativas": active_automations,
            "processos_ativos": active_processes,
            "prazos_hoje": emails_today,
            "tempo_economizado": f"{active_processes * 0.5}h" # Estimativa: 30min por processo
        })