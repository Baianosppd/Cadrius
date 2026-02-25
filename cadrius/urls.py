# julliodutra/cadrius/cadrius-d2664e7d9d3cdaaeb4729d29c9fafb13438707c0/cadrius/urls.py

from django.contrib import admin
from django.urls import path, include, re_path
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework import routers
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework import permissions 
from core.views import DashboardStatsView

# Importações corretas das Views criadas no passo anterior
from core.views import ( # Views de páginas/core
    health_check,
    login_view,
    register_view,
    dashboard_view
)
from accounts.views import RegisterUserView, GetUserProfileView, CustomTokenObtainPairView # Novas views de usuário

from emails.views import (
    MailBoxViewSet, 
    EmailMessageViewSet, 
    IntegrationConfigViewSet, 
    ExtractionProfileViewSet, 
    AutomationRuleViewSet
)

# Configuração do Swagger
schema_view = get_schema_view(
   openapi.Info(
      title="Cadrius API",
      default_version='v1',
      description="API REST para Automação Jurídica",
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)

# Roteador DRF
router = routers.DefaultRouter()
router.register(r'mailboxes', MailBoxViewSet)
router.register(r'emails', EmailMessageViewSet)
router.register(r'integration-configs', IntegrationConfigViewSet)
router.register(r'extraction-profiles', ExtractionProfileViewSet)
router.register(r'automation-rules', AutomationRuleViewSet)

urlpatterns = [
    # --- Rotas de Frontend (HTML) ---
    path('', login_view, name='login_entry'),           # Rota Raiz -> Login
    path('register/', register_view, name='register_entry'), # Rota -> Cadastro
    path('dashboard/', dashboard_view, name='dashboard'),    # Rota -> Aplicação Principal

    # --- Rotas de Admin e Utils ---
    path('admin/', admin.site.urls),
    path('healthz/', health_check, name='healthz'),

    # --- Rotas da API V1 ---
    path('api/v1/', include(router.urls)),

    # --- Autenticação API (JWT) ---
    path('api/v1/auth/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'), # Rota corrigida
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/register/', RegisterUserView.as_view(), name='user_register'), # Rota corrigida
    path('api/v1/auth/user/', GetUserProfileView.as_view(), name='user_profile'), # Rota corrigida
    path('api/v1/dashboard/stats/', DashboardStatsView.as_view(), name='dashboard_stats'),

    # --- Documentação ---
    re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]