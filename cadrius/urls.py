from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

# --- Views ---
from accounts.views import (
    RegisterUserView,
    RegisterCompanyView,
    GetUserProfileView,
    UpdateUserProfileView,
    ChangePasswordView,
    TeamMemberListCreateView,
    MemberCreditLimitView,
    TeamCreditsSummaryView,
    FuncionariosListView,
    PermissionGroupListView,
    CustomTokenObtainPairView,
    ThrottledTokenRefreshView,
    LogoutView,
)
from core.views import health_check, readiness_check, DashboardStatsView, ActivitiesView, SyncHistoryView
from documents.views import (
    ClientDocumentCreateView,
    DocumentDownloadView,
    DocumentListCreateView,
)
from emails.views import MailBoxViewSet, EmailMessageViewSet, ExtractionProfileViewSet
from tasks.views import UserTaskViewSet
from workflows.views import WorkflowViewSet, AutomationStatsView

# --- Roteador DRF (Endpoints Automáticos) ---
router = routers.DefaultRouter()
router.register(r'mailboxes', MailBoxViewSet, basename='mailbox')
router.register(r'emails', EmailMessageViewSet, basename='email')
router.register(r'extraction-profiles', ExtractionProfileViewSet, basename='extraction-profile')
router.register(r'workflows', WorkflowViewSet, basename='workflow')
router.register(r'tasks', UserTaskViewSet, basename='task')

# --- Mapeamento Final de URLs ---
urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', health_check, name='healthz'),
    path('readyz/', readiness_check, name='readyz'),

    # --- Rotas Base da API V1 ---
    path('api/v1/', include(router.urls)),

    # --- Autenticação (JWT) ---
    path('api/v1/auth/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', ThrottledTokenRefreshView.as_view(), name='token_refresh'),
    path('api/v1/auth/logout/', LogoutView.as_view(), name='auth_logout'),
    path('api/v1/auth/register/', RegisterUserView.as_view(), name='user_register'),
    path('api/v1/auth/register/empresa/', RegisterCompanyView.as_view(), name='company_register'),
    path('api/v1/auth/user/', GetUserProfileView.as_view(), name='user_profile'),
    path('api/v1/auth/profile/', UpdateUserProfileView.as_view(), name='user_profile_update'),
    path('api/v1/auth/change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('api/v1/teams/members/', TeamMemberListCreateView.as_view(), name='team-members'),
    path(
        'api/v1/teams/members/<uuid:pk>/credits/',
        MemberCreditLimitView.as_view(),
        name='team-member-credits',
    ),
    path('api/v1/teams/credits/', TeamCreditsSummaryView.as_view(), name='team-credits'),
    path('api/v1/funcionarios/', FuncionariosListView.as_view(), name='funcionarios-list'),
    path('api/v1/documentos/', DocumentListCreateView.as_view(), name='documentos-list'),
    path(
        'api/v1/documentos/cliente/',
        ClientDocumentCreateView.as_view(),
        name='documentos-cliente-create',
    ),
    path(
        'api/v1/documentos/<int:pk>/download/',
        DocumentDownloadView.as_view(),
        name='documentos-download',
    ),
    path(
        'api/v1/teams/permission-groups/',
        PermissionGroupListView.as_view(),
        name='team-permission-groups',
    ),
    
    path('api/v1/dashboard/stats/', DashboardStatsView.as_view(), name='dashboard_stats'),
    path('api/v1/activities/', ActivitiesView.as_view(), name='activities'),
    path('api/v1/sync-history/', SyncHistoryView.as_view(), name='sync-history'),
    path('api/v1/notifications/', include('notifications.urls')),
    path('api/v1/automations/stats/', AutomationStatsView.as_view(), name='automation_stats'),
    path('api/workflows/', include('workflows.urls')),

    
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('api/v1/audit/', include('audit.urls')),
    path('api/v1/', include('privacy.urls')),
    path('api/v1/ai/', include('aigov.urls')),
    path('api/billing/', include('billing.urls')),
    path('api/webhooks/', include('webhooks.urls')),
]