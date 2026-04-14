from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

# --- Views ---
from accounts.views import RegisterUserView, GetUserProfileView, CustomTokenObtainPairView
from core.views import health_check, DashboardStatsView
from emails.views import MailBoxViewSet, EmailMessageViewSet, ExtractionProfileViewSet
from workflows.views import WorkflowViewSet

# --- Roteador DRF (Endpoints Automáticos) ---
router = routers.DefaultRouter()
router.register(r'mailboxes', MailBoxViewSet, basename='mailbox')
router.register(r'emails', EmailMessageViewSet, basename='email')
router.register(r'extraction-profiles', ExtractionProfileViewSet, basename='extraction-profile')
router.register(r'workflows', WorkflowViewSet, basename='workflow')

# --- Mapeamento Final de URLs ---
urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', health_check, name='healthz'),

    # --- Rotas Base da API V1 ---
    path('api/v1/', include(router.urls)),

    # --- Autenticação (JWT) ---
    path('api/v1/auth/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/register/', RegisterUserView.as_view(), name='user_register'),
    path('api/v1/auth/user/', GetUserProfileView.as_view(), name='user_profile'),
    
    path('api/v1/dashboard/stats/', DashboardStatsView.as_view(), name='dashboard_stats'),
    path('api/workflows/', include('workflows.urls')),

    
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('api/billing/', include('billing.urls')),
    path('api/webhooks/', include('webhooks.urls')),
]