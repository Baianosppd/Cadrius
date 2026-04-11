from django.contrib import admin
from django.urls import path, include, re_path
from rest_framework import routers, permissions
from rest_framework_simplejwt.views import TokenRefreshView
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# --- Views ---
from accounts.views import RegisterUserView, GetUserProfileView, CustomTokenObtainPairView
from core.views import health_check, DashboardStatsView
from emails.views import MailBoxViewSet, EmailMessageViewSet, ExtractionProfileViewSet
from workflows.views import WorkflowViewSet

# --- Configuração do Swagger (Documentação da API) ---
schema_view = get_schema_view(
   openapi.Info(
      title="Cadrius AI - API",
      default_version='v1',
      description="API REST para Automação Jurídica e Orquestração",
   ),
   public=True,
   permission_classes=(permissions.AllowAny,),
)

# --- Roteador DRF (Endpoints Automáticos) ---
router = routers.DefaultRouter()
router.register(r'mailboxes', MailBoxViewSet, basename='mailbox')
router.register(r'emails', EmailMessageViewSet, basename='email')
router.register(r'extraction-profiles', ExtractionProfileViewSet, basename='extraction-profile')
router.register(r'workflows', WorkflowViewSet, basename='workflow')

# --- Mapeamento Final de URLs ---
urlpatterns = [
    # --- Rotas de Admin e Health ---
    path('admin/', admin.site.urls),
    path('healthz/', health_check, name='healthz'),

    # --- Rotas Base da API V1 ---
    path('api/v1/', include(router.urls)),

    # --- Autenticação (JWT) ---
    path('api/v1/auth/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/register/', RegisterUserView.as_view(), name='user_register'),
    path('api/v1/auth/user/', GetUserProfileView.as_view(), name='user_profile'),
    
    # --- Dashboards e Estatísticas ---
    path('api/v1/dashboard/stats/', DashboardStatsView.as_view(), name='dashboard_stats'),

    # --- Rotas de Workflows e Webhooks ---
    path('api/workflows/', include('workflows.urls')),

    # --- Documentação da API (Swagger/ReDoc) ---
    re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

   #-- Rotas de Cobrança e Assinaturas (Stripe) ---
    path('api/billing/', include('billing.urls')),
]