from django.contrib import admin
from assistant.mcp import McpView
from django.urls import path, re_path, include
from rest_framework import routers
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

# --- Views ---
from accounts.sso import SsoCallbackView, SsoStartView
from accounts.password_reset import PasswordResetConfirmView, PasswordResetRequestView
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
from accounts import mfa_api
from support.urls import staff_urlpatterns as support_staff_urls
from marketing.urls import staff_urlpatterns as marketing_staff_urls
from integrations.api import ConnectionDeleteView, ConnectionListCreateView
from core.views import health_check, readiness_check, DashboardStatsView, ActivitiesView, SyncHistoryView
from documents.views import (
    ClientDocumentCreateView,
    DocumentDetailView,
    DocumentExtractionConfirmView,
    DocumentExtractionReprocessView,
    DocumentExtractionUndoView,
    DocumentExtractionView,
    DocumentDownloadView,
    DocumentListCreateView,
)
from emails.views import MailBoxViewSet, EmailMessageViewSet, ExtractionProfileViewSet
from tasks.views import UserTaskViewSet
from workflows.views import WorkflowViewSet, AutomationStatsView
from compliance import urls as compliance_urls

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
    re_path(r'^api/v1/auth/(?P<provider>google|microsoft)/callback/$', SsoCallbackView.as_view(), name='sso_callback'),
    re_path(r'^api/v1/auth/(?P<provider>google|microsoft)/$', SsoStartView.as_view(), name='sso_start'),
    path('api/v1/auth/register/', RegisterUserView.as_view(), name='user_register'),
    path('api/v1/auth/register/empresa/', RegisterCompanyView.as_view(), name='company_register'),
    path('api/v1/auth/user/', GetUserProfileView.as_view(), name='user_profile'),
    path('api/v1/auth/profile/', UpdateUserProfileView.as_view(), name='user_profile_update'),
    path('api/v1/auth/change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('api/v1/auth/password-reset/', PasswordResetRequestView.as_view(), name='password_reset'),
    path('api/v1/auth/password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('api/v1/auth/mfa/', mfa_api.MFAStatusView.as_view(), name='mfa_status'),
    path('api/v1/auth/mfa/setup/', mfa_api.MFASetupView.as_view(), name='mfa_setup'),
    path('api/v1/auth/mfa/confirm/', mfa_api.MFAConfirmView.as_view(), name='mfa_confirm'),
    path('api/v1/auth/mfa/disable/', mfa_api.MFADisableView.as_view(), name='mfa_disable'),
    path('api/v1/auth/mfa/recovery-codes/', mfa_api.MFARecoveryCodesView.as_view(), name='mfa_recovery_codes'),
    path('api/v1/auth/mfa/verify/', mfa_api.MFAVerifyView.as_view(), name='mfa_verify'),
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
    path('api/v1/documentos/<int:pk>/', DocumentDetailView.as_view(), name='documentos-detail'),
    path('api/v1/documentos/<int:pk>/extraction/', DocumentExtractionView.as_view(), name='documentos-extraction'),
    path('api/v1/documentos/<int:pk>/extraction/reprocess/', DocumentExtractionReprocessView.as_view(),
         name='documentos-extraction-reprocess'),
    path('api/v1/documentos/<int:pk>/extraction/confirm/', DocumentExtractionConfirmView.as_view(),
         name='documentos-extraction-confirm'),
    path('api/v1/documentos/<int:pk>/extraction/undo-auto/', DocumentExtractionUndoView.as_view(), name='documentos-extraction-undo'),
    path(
        'api/v1/teams/permission-groups/',
        PermissionGroupListView.as_view(),
        name='team-permission-groups',
    ),
    
    path('api/v1/dashboard/stats/', DashboardStatsView.as_view(), name='dashboard_stats'),
    path('api/v1/activities/', ActivitiesView.as_view(), name='activities'),
    path('api/v1/sync-history/', SyncHistoryView.as_view(), name='sync-history'),
    path('api/v1/notifications/', include('notifications.urls')),
    path('api/v1/integrations/google-calendar/', include('gcal.urls')),
    path('api/v1/integrations/', include('integrations.urls_v1')),
    path('api/v1/research/', include('research.urls')),
    path('api/v1/erp/', include('erp.urls')),
    path('api/v1/backoffice/', include('backoffice.urls')),
    path('api/v1/backoffice/', include(support_staff_urls)),
    path('api/v1/contacts/', include('contacts.urls')),
    path('api/v1/imports/', include('imports.urls')),
    path('api/v1/support/', include('support.urls')),
    path('api/v1/forense/', include('forense.urls')),
    path('api/v1/publications/', include('publications.urls')),
    path('api/v1/minutas/', include('minutas.urls')),
    path('api/v1/marketing/', include('marketing.urls')),
    path('api/v1/carteira/', include('carteira.urls')),
    path('api/v1/portal/', include('portal.urls')),
    path('api/v1/backoffice/', include(marketing_staff_urls)),
    path('api/v1/brain/', include('brain.urls')),
    path('api/v1/connections/', ConnectionListCreateView.as_view(), name='connections'),
    path('api/v1/connections/<int:pk>/', ConnectionDeleteView.as_view(), name='connection-detail'),
    path('api/v1/automations/stats/', AutomationStatsView.as_view(), name='automation_stats'),
    path('api/v1/automations/', include('automations.urls')),
    path('api/workflows/', include('workflows.urls')),

    
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    path('api/v1/audit/', include('audit.urls')),
    path('api/v1/', include('privacy.urls')),
    path('api/v1/ai/', include('aigov.urls')),
    path('api/v1/assistant/', include('assistant.urls')),
    path('mcp/', McpView.as_view(), name='mcp'),                      # conector Claude/ChatGPT (CAD-222)
    path('mcp/<str:token>/', McpView.as_view(), name='mcp-token'),
    path('api/v1/security/', include((compliance_urls.api_urlpatterns, 'security-api'))),
    path('security-center/', include('compliance.urls')),
    path('api/billing/', include('billing.urls')),
    path('api/webhooks/', include('webhooks.urls')),
]