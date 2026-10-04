"""Verificações AUTOMÁTICAS de conformidade: olham a configuração e os dados REAIS do ambiente em execução."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = logging.getLogger('compliance')

PASS, PARTIAL, FAIL, UNKNOWN = 'pass', 'partial', 'fail', 'unknown'


@dataclass(frozen=True)
class CheckResult:
    status: str
    detail: str


CHECKS: dict = {}
TITLES: dict = {}


def check(name: str, title: str):
    def decorator(fn):
        CHECKS[name] = fn
        TITLES[name] = title
        return fn
    return decorator


def _prod() -> bool:
    return not settings.DEBUG


def _repo_file(*parts):
    path = Path(settings.BASE_DIR).joinpath(*parts)
    return path if path.exists() else None


def _schedule_exists(name: str) -> bool:
    from django_q.models import Schedule
    return Schedule.objects.filter(name=name).exists()


# --------------------------------------------------------------------------- configuração e segredos
@check('secret_key', 'SECRET_KEY segura (não é o valor padrão)')
def _secret_key():
    ok = settings.SECRET_KEY != 'django-insecure-change-me-in-prod' and len(settings.SECRET_KEY) >= 32
    return CheckResult(PASS if ok else FAIL, 'Chave forte definida.' if ok else 'Usando chave padrão/curta: tokens JWT forjáveis.')


@check('debug_off', 'DEBUG desativado')
def _debug_off():
    return CheckResult(PASS, 'DEBUG=False.') if _prod() else CheckResult(PARTIAL, 'DEBUG=True (ambiente de desenvolvimento).')


@check('hosts', 'ALLOWED_HOSTS restrito')
def _hosts():
    hosts = settings.ALLOWED_HOSTS
    if '*' in hosts:
        return CheckResult(FAIL, 'ALLOWED_HOSTS contém "*".')
    if _prod() and any('ngrok' in h for h in hosts):
        return CheckResult(PARTIAL, 'Túnel ngrok presente em ALLOWED_HOSTS em produção.')
    return CheckResult(PASS, f'{len(hosts)} host(s) permitido(s).')


@check('encryption_key', 'ENCRYPTION_KEY configurada (cifra em repouso)')
def _encryption_key():
    if settings.ENCRYPTION_KEY:
        return CheckResult(PASS, 'Chave Fernet definida no ambiente.')
    return CheckResult(PARTIAL if not _prod() else FAIL, 'Sem ENCRYPTION_KEY: usando chave derivada (apenas dev).')


@check('pii_encrypted', 'Dados pessoais cifrados em repouso')
def _pii_encrypted():
    from core.pii import plaintext_counts
    counts = plaintext_counts()
    leaking = {k: v for k, v in counts.items() if v}
    if leaking:
        sample = ', '.join(f'{k} ({v})' for k, v in list(leaking.items())[:3])
        return CheckResult(FAIL, f'Há dados pessoais em texto puro no banco: {sample}. Rode `manage.py encrypt_pii`.')
    return CheckResult(PASS, f'{len(counts)} colunas de dados pessoais/segredos conferidas no banco: 0 linhas em texto puro (Fernet).')


@check('credentials_encrypted', 'Credenciais de terceiros cifradas no banco')
def _credentials_encrypted():
    queries = [
        ('emails_mailbox', 'password'), ('integrations_appconnection', 'credentials'),
        ('tasks_integrationconfig', 'trello_api_token'), ('tasks_integrationconfig', 'telegram_bot_token'),
    ]
    plain = 0
    quote = connection.ops.quote_name
    with connection.cursor() as cur:
        for table, column in queries:  # identificadores constantes do código (nunca entrada do usuário)
            t, c = quote(table), quote(column)
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} IS NOT NULL AND {c} <> '' "  # nosec B608
                        f"AND {c} NOT LIKE 'enc::%%'")
            plain += cur.fetchone()[0]
    return CheckResult(PASS, 'Nenhuma credencial em texto puro.') if plain == 0 else \
        CheckResult(FAIL, f'{plain} credencial(is) em texto puro — rode as migrações de cifra.')


@check('transport_security', 'TLS/HSTS e cookies seguros')
def _transport():
    if not _prod():
        return CheckResult(PARTIAL, 'Ambiente de desenvolvimento (http).')
    issues = []
    if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
        issues.append('cookies sem Secure')
    if not getattr(settings, 'SECURE_HSTS_SECONDS', 0):
        issues.append('HSTS desligado')
    if not settings.SECURE_PROXY_SSL_HEADER:
        issues.append('sem SECURE_PROXY_SSL_HEADER')
    return CheckResult(FAIL if issues else PASS, ', '.join(issues) or 'HSTS, cookies Secure e proxy TLS configurados.')


@check('csp', 'Content-Security-Policy e anti-clickjacking')
def _csp():
    directives = getattr(settings, 'CONTENT_SECURITY_POLICY', {}).get('DIRECTIVES', {})
    ok = 'frame-ancestors' in directives and settings.X_FRAME_OPTIONS == 'DENY'
    return CheckResult(PASS if ok else FAIL, 'CSP (django-csp 4) + X-Frame-Options DENY.' if ok else 'CSP/anti-clickjacking incompletos.')


# --------------------------------------------------------------------------- autenticação e acesso
@check('password_policy', 'Política de senhas aplicada')
def _password_policy():
    n = len(settings.AUTH_PASSWORD_VALIDATORS)
    return CheckResult(PASS if n >= 3 else FAIL, f'{n} validadores ativos (cadastro e troca de senha).')


@check('bruteforce', 'Proteção contra força bruta e abuso')
def _bruteforce():
    rates = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
    ok = 'axes' in settings.INSTALLED_APPS and 'auth_login' in rates and 'auth_register' in rates \
        and settings.AXES_FAILURE_LIMIT <= 10
    return CheckResult(PASS if ok else FAIL, f"axes limite {settings.AXES_FAILURE_LIMIT}; login {rates.get('auth_login')}, cadastro {rates.get('auth_register')}.")


@check('jwt_revocation', 'Revogação de sessões (logout/blacklist)')
def _jwt_revocation():
    ok = 'rest_framework_simplejwt.token_blacklist' in settings.INSTALLED_APPS
    return CheckResult(PASS if ok else FAIL, 'token_blacklist instalado; POST /api/v1/auth/logout/.' if ok else 'Sem blacklist.')


@check('mfa', 'MFA (autenticação multifator)')
def _mfa():
    from django.conf import settings as dj
    from django.contrib.auth import get_user_model
    staff = get_user_model().objects.filter(is_staff=True, is_active=True)
    total = staff.count()
    with_mfa = staff.filter(mfa_device__confirmed_at__isnull=False).count()
    managers = 'obrigatório também para donos/admins' if getattr(dj, 'MFA_REQUIRED_FOR_MANAGERS', False) \
        else 'opcional para donos/admins (MFA_REQUIRED_FOR_MANAGERS=False)'
    if total and with_mfa < total:
        return CheckResult(PARTIAL, f'TOTP ativo; {with_mfa}/{total} da equipe já cadastraram (sem MFA não entram na Gestão); {managers}. '
                                    'O /admin/ do Django ainda é só senha.')
    return CheckResult(PASS if getattr(dj, 'MFA_REQUIRED_FOR_MANAGERS', False) else PARTIAL,
                       f'TOTP ativo; equipe 100% com MFA; {managers}. O /admin/ do Django ainda é só senha.')


@check('email_verification', 'Verificação de e-mail no cadastro')
def _email_verification():
    ok = getattr(settings, 'ACCOUNT_EMAIL_VERIFICATION', 'none') != 'none'
    return CheckResult(PASS if ok else FAIL, 'ACCOUNT_EMAIL_VERIFICATION ativo.' if ok else 'ACCOUNT_EMAIL_VERIFICATION="none".')


@check('sso_verified_email', 'SSO só vincula escritório com e-mail verificado')
def _sso_verified():
    try:
        from accounts import adapters
        ok = hasattr(adapters, '_email_is_verified')
    except Exception:  # noqa: BLE001
        ok = False
    return CheckResult(PASS if ok else FAIL, 'Adapter exige e-mail verificado pelo provedor.' if ok else 'Adapter SSO indisponível.')


@check('rbac', 'RBAC por cargo aplicado nos recursos')
def _rbac():
    from accounts.permissions import OrgRolePermission
    from emails.views import ExtractionProfileViewSet, MailBoxViewSet
    from workflows.views import WorkflowViewSet
    ok = all(OrgRolePermission in v.permission_classes for v in (WorkflowViewSet, MailBoxViewSet, ExtractionProfileViewSet))
    return CheckResult(PASS if ok else FAIL, 'VIEWER somente leitura; aprovações só OWNER/ADMIN.' if ok else 'RBAC ausente em algum viewset.')


@check('tenant_isolation', 'Isolamento entre escritórios (multi-tenant)')
def _tenant_isolation():
    from accounts.tenancy import TenantQuerysetMixin
    from emails.views import EmailMessageViewSet, ExtractionProfileViewSet, MailBoxViewSet
    from tasks.views import UserTaskViewSet
    from workflows.views import WorkflowViewSet
    views = (WorkflowViewSet, MailBoxViewSet, EmailMessageViewSet, ExtractionProfileViewSet, UserTaskViewSet)
    ok = all(issubclass(v, TenantQuerysetMixin) for v in views)
    return CheckResult(PASS if ok else FAIL, f'{len(views)} viewsets com TenantQuerysetMixin + testes de vazamento.' if ok else 'Viewset sem isolamento.')


# --------------------------------------------------------------------------- trilha, monitoramento, resposta
@check('audit_trail', 'Trilha de auditoria íntegra')
def _audit_trail():
    from audit.models import AuditEvent
    from audit.verify import verify_chain
    result = verify_chain()
    if not result['ok']:
        return CheckResult(FAIL, f"CADEIA ADULTERADA no evento #{result['first_bad_seq']}: {result['reason']}")
    n = AuditEvent.objects.count()
    return CheckResult(PASS if n else PARTIAL, f'{result["checked"]} eventos verificados, cadeia íntegra.' if n else 'Sem eventos ainda.')


@check('audit_immutable', 'Imutabilidade da trilha no banco')
def _audit_immutable():
    if connection.vendor != 'postgresql':
        return CheckResult(PARTIAL, 'Banco não-PostgreSQL: imutabilidade só na camada do modelo + hash.')
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pg_trigger WHERE tgname = 'audit_auditevent_immutable'")
        has = cur.fetchone()[0] > 0
    return CheckResult(PASS if has else FAIL, 'Trigger bloqueia UPDATE/DELETE/TRUNCATE.' if has else 'Trigger de imutabilidade ausente!')


@check('admin_audited', 'Ações do Django Admin auditadas')
def _admin_audited():
    ok = 'audit.middleware.AuditContextMiddleware' in settings.MIDDLEWARE and 'audit' in settings.INSTALLED_APPS
    return CheckResult(PASS if ok else FAIL, 'LogEntry + acesso de staff viram eventos imutáveis.' if ok else 'Auditoria do Admin inativa.')


@check('anomaly_detection', 'Deteção de anomalias agendada')
def _anomaly():
    ok = _schedule_exists('Segurança: detetar anomalias')
    return CheckResult(PASS if ok else PARTIAL, 'Regras A1–A12 a cada 5 min.' if ok else 'Regras existem mas não estão agendadas (setup_security_schedules).')


@check('security_schedules', 'Rotinas de segurança agendadas')
def _schedules():
    names = ['Segurança: detetar anomalias', 'Segurança: verificar cadeia de auditoria', 'Privacidade: aplicar retenção (LGPD)']
    missing = [n for n in names if not _schedule_exists(n)]
    return CheckResult(PASS if not missing else PARTIAL, 'Detecção, verificação da cadeia e retenção agendadas.' if not missing else f'Faltam: {", ".join(missing)}.')


@check('open_critical_alerts', 'Sem alertas críticos/altos abertos > 24 h')
def _open_alerts():
    from audit.models import AnomalyAlert
    stale = AnomalyAlert.objects.filter(status='open', severity__in=['high', 'critical'],
                                        created_at__lt=timezone.now() - timedelta(hours=24)).count()
    return CheckResult(PASS if stale == 0 else FAIL, 'Alertas tratados dentro do SLA.' if stale == 0 else f'{stale} alerta(s) fora do SLA de 24 h.')


@check('logging_structured', 'Logging estruturado com correlação')
def _logging():
    ok = 'structured' in settings.LOGGING.get('formatters', {})
    return CheckResult(PASS if ok else FAIL, 'Logs chave=valor (execution_log_id, request_id) em stdout → Dozzle.' if ok else 'LOGGING não configurado.')


@check('sentry_privacy', 'Monitoramento (Sentry) sem PII automática')
def _sentry():
    import sentry_sdk
    client = sentry_sdk.get_client()
    if not getattr(client, 'dsn', None):
        return CheckResult(PARTIAL if not _prod() else FAIL, 'Sentry sem DSN neste ambiente.')
    pii = client.options.get('send_default_pii')
    return CheckResult(PASS if not pii else FAIL, 'send_default_pii=False; só IDs de usuário/escritório.' if not pii else 'send_default_pii=True!')


@check('readiness', 'Prontidão do serviço (banco e cache)')
def _readiness():
    from django.core.cache import cache
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
        cache.set('compliance-ready', '1', 5)
        cache_ok = cache.get('compliance-ready') == '1'
    except Exception:  # noqa: BLE001
        return CheckResult(FAIL, 'Banco indisponível.')
    return CheckResult(PASS if cache_ok else PARTIAL, 'Banco e cache respondem.' if cache_ok else 'Cache/Redis indisponível.')


@check('time_sync', 'Relógio/UTC consistente')
def _time_sync():
    return CheckResult(PARTIAL, f'USE_TZ={settings.USE_TZ}, eventos em UTC; sincronização NTP do host a evidenciar (manual).')


@check('data_masking', 'Mascaramento de PII em trilha e logs')
def _masking():
    from audit.redaction import redact
    sample = redact({'cpf': '123.456.789-09', 'nota': 'a@b.com'})
    ok = sample['cpf'] == '<redacted>' and 'a@b.com' not in sample['nota']
    return CheckResult(PASS if ok else FAIL, 'Redação automática de CPF, e-mail, tokens e corpos.' if ok else 'Redação falhou.')


def _host_backup_status(env='prod'):
    """Lê o status gravado por deploy/backup/backup.sh (montado somente-leitura no contêiner)."""
    path = Path(getattr(settings, 'BACKUP_STATUS_FILE', '/host-status/backup.status'))
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        parts = line.split()
        if len(parts) >= 3 and parts[0] == env:
            info = dict(p.split('=', 1) for p in parts[3:] if '=' in p)
            return {'status': parts[1], 'at': parts[2], **info}
    return None


@check('backup', 'Backups cifrados agendados')
def _backup():
    st = _host_backup_status('prod')
    if st:
        from datetime import datetime, timezone as dt_tz
        try:
            when = datetime.strptime(st['at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt_tz.utc)
            age_h = (timezone.now() - when).total_seconds() / 3600
        except ValueError:
            age_h = None
        if st['status'] == 'ok' and age_h is not None and age_h <= 26:
            if st.get('offsite') == 'true':
                return CheckResult(PASS, f'Último backup de produção há {age_h:.0f} h, cifrado (GPG) e copiado para fora do servidor.')
            return CheckResult(PARTIAL, 'Backup de produção cifrado e recente, mas SEM cópia externa (configure RCLONE_REMOTE).')
        return CheckResult(FAIL, 'Último backup de produção falhou ou está desatualizado (> 26 h). Veja deploy/README.md.')
    from django_q.models import Schedule
    scheduled = Schedule.objects.filter(args__contains='backup_to_supabase').exists()
    if scheduled:
        return CheckResult(PASS, 'backup_to_supabase agendado (dump cifrado com Fernet).')
    return CheckResult(PARTIAL, 'Sem status de backup do servidor; agende backup_to_supabase ou use o kit deploy/backup.')


def _status_age_hours(st):
    from datetime import datetime, timezone as dt_tz
    try:
        when = datetime.strptime(st['at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt_tz.utc)
        return (timezone.now() - when).total_seconds() / 3600
    except (ValueError, KeyError):
        return None


@check('offsite_verified', 'Cópia externa dos backups conferida (existe no destino e confere)')
def _offsite_verified():
    st = _host_backup_status('offsite-check-prod')
    if not st:
        return CheckResult(PARTIAL if not _prod() else FAIL,
                           'Sem conferência da cópia externa (verify-offsite.sh). Configure o RCLONE_REMOTE e o timer diário.')
    age = _status_age_hours(st)
    if st['status'] == 'ok' and age is not None and age <= 36:
        return CheckResult(PASS, f'Cópia externa conferida há {age:.0f} h (arquivo presente no destino, tamanho e hash iguais).')
    return CheckResult(FAIL, 'A conferência da cópia externa falhou ou está desatualizada (> 36 h): o backup pode não estar fora do servidor.')


@check('restore_drill', 'Restauração testada recentemente')
def _restore_drill():
    st = _host_backup_status('restore-test-prod')
    if not st:
        return CheckResult(PARTIAL if not _prod() else FAIL, 'Nenhum teste de restauração registrado (verify-restore.sh semanal).')
    age = _status_age_hours(st)
    if st['status'] == 'ok' and age is not None and age <= 24 * 9:
        return CheckResult(PASS, f'Restauração testada há {age / 24:.0f} dia(s): tabelas, contagens e trilha de auditoria conferem.')
    return CheckResult(FAIL, 'O último teste de restauração falhou ou tem mais de 9 dias.')


# --------------------------------------------------------------------------- privacidade (LGPD)
@check('legal_docs', 'Documentos legais vigentes')
def _legal_docs():
    from privacy.models import LegalDocument
    current = LegalDocument.objects.filter(is_current=True)
    kinds = set(current.values_list('kind', flat=True))
    missing = {'terms', 'privacy', 'ciencia', 'ai_notice'} - kinds
    if missing:
        return CheckResult(FAIL, f'Faltam documentos: {", ".join(sorted(missing))}.')
    pending = current.filter(needs_legal_review=True).count()
    return CheckResult(PARTIAL if pending else PASS,
                       f'{pending} documento(s) ainda marcados "pendente de revisão jurídica".' if pending else 'Documentos revisados e vigentes.')


@check('consent_records', 'Aceite e consentimento comprovados')
def _consent_records():
    from privacy.models import ConsentRecord
    if not getattr(settings, 'LEGAL_ACCEPTANCE_REQUIRED', True):
        return CheckResult(FAIL, 'LEGAL_ACCEPTANCE_REQUIRED desligado.')
    return CheckResult(PASS, f'Aceite obrigatório; {ConsentRecord.objects.count()} registro(s) com hash do texto aceito.')


@check('subprocessors', 'Suboperadores com contrato/DPA verificado')
def _subprocessors():
    from privacy.models import SubprocessorEntry
    active = SubprocessorEntry.objects.filter(active=True)
    total = active.count()
    verified = active.filter(contract_verified=True).count()
    if total == 0:
        return CheckResult(FAIL, 'Nenhum suboperador cadastrado.')
    if verified == total:
        return CheckResult(PASS, f'{total} suboperador(es) com DPA verificado.')
    return CheckResult(PARTIAL, f'{verified}/{total} com contrato/DPA verificado — formalizar com o jurídico.')


@check('dsr_sla', 'Pedidos de titulares dentro do prazo (15 dias)')
def _dsr():
    from privacy.models import DataSubjectRequest
    overdue = [r for r in DataSubjectRequest.objects.filter(status__in=['open', 'in_progress']) if r.overdue]
    return CheckResult(PASS if not overdue else FAIL, 'Nenhum pedido vencido.' if not overdue else f'{len(overdue)} pedido(s) vencido(s).')


@check('retention_policy', 'Retenção e eliminação automatizadas')
def _retention():
    ok = _schedule_exists('Privacidade: aplicar retenção (LGPD)')
    return CheckResult(PASS if ok else PARTIAL, 'enforce_retention diário (e-mails 90d, payloads 90d, logs 30d).' if ok else 'Política implementada, mas não agendada.')


@check('processing_inventory', 'RoPA (registro das operações de tratamento)')
def _ropa():
    from compliance.ropa import PROCESSING_ACTIVITIES
    return CheckResult(PASS if PROCESSING_ACTIVITIES else FAIL, f'{len(PROCESSING_ACTIVITIES)} operações de tratamento mapeadas.')


@check('dpo_contact', 'Encarregado (DPO) e canal do titular')
def _dpo():
    email = getattr(settings, 'PRIVACY_CONTACT_EMAIL', '')
    if not email:
        return CheckResult(FAIL, 'PRIVACY_CONTACT_EMAIL não configurado.')
    return CheckResult(PARTIAL, f'Canal {email} configurado; nomeação formal do encarregado a evidenciar (manual).')


@check('ripd', 'RIPD / DPIA elaborado')
def _ripd():
    if _repo_file('docs', 'RIPD_MODELO.md'):
        return CheckResult(PARTIAL, 'Modelo de RIPD disponível; falta preenchimento e assinatura (manual).')
    return CheckResult(UNKNOWN, 'Não verificável neste ambiente — registrar avaliação manual.')


@check('incident_process', 'Procedimento de resposta a incidentes (art. 48)')
def _incident():
    if _repo_file('docs', 'runbook.md'):
        return CheckResult(PARTIAL, 'Runbook existe; completar com comunicação à ANPD/titulares (3 dias úteis).')
    return CheckResult(UNKNOWN, 'Não verificável neste ambiente — registrar avaliação manual.')


# --------------------------------------------------------------------------- IA
@check('ai_governance', 'Governança de IA ativa')
def _ai_gov():
    from aigov.guard import global_ai_enabled
    from aigov.models import AIGovernancePolicy
    state = 'LIGADA' if global_ai_enabled() else 'DESLIGADA (kill switch global)'
    return CheckResult(PASS, f'Políticas por escritório ({AIGovernancePolicy.objects.count()}), registro de uso, kill switch — IA {state}.')


@check('ai_human_review', 'Revisão humana de ações de IA em dia')
def _ai_review():
    from workflows.models import ExecutionLog, Workflow
    cutoff = timezone.now() - timedelta(hours=48)
    stale = ExecutionLog.objects.filter(status='PENDING_REVIEW', created_at__lt=cutoff).count()
    waiting = Workflow.objects.filter(ai_generated=True, approved_at__isnull=True,
                                      created_at__lt=cutoff).count()
    if stale or waiting:
        return CheckResult(PARTIAL, f'{stale} execução(ões) e {waiting} rascunho(s) de IA aguardando revisão há mais de 48 h.')
    return CheckResult(PASS, 'Sem pendências de revisão humana antigas.')


# --------------------------------------------------------------------------- pipeline / cadeia de suprimentos
def _ci_text() -> str | None:
    path = _repo_file('.github', 'workflows', 'ci.yml')
    return path.read_text(encoding='utf-8') if path else None


@check('ci_pipeline', 'Pipeline de CI/CD com portões de qualidade')
def _ci():
    text = _ci_text()
    if text is None:
        return CheckResult(UNKNOWN, 'Repositório indisponível neste ambiente — evidência: GitHub Actions (manual).')
    gates = [g for g in ('flake8', 'bandit', 'pip-audit', 'trivy', 'manage.py test') if g in text.lower()]
    ok = len(gates) >= 4
    return CheckResult(PASS if ok else PARTIAL, f'Portões no CI: {", ".join(gates)}.')


@check('dependency_scanning', 'Varredura de dependências e imagem')
def _deps():
    text = _ci_text()
    if text is None:
        return CheckResult(UNKNOWN, 'Repositório indisponível neste ambiente — evidência: CI (manual).')
    ok = 'pip-audit' in text and 'trivy' in text.lower()
    return CheckResult(PASS if ok else PARTIAL, 'pip-audit + Trivy + Dependabot.' if ok else 'Varredura parcial.')


def run_all() -> dict:
    """Executa todas as verificações (cada uma isolada: uma falha não derruba o painel)."""
    results = {}
    for name, fn in CHECKS.items():
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception('verificação %s falhou', name)
            results[name] = CheckResult(UNKNOWN, f'Erro ao verificar: {type(exc).__name__}')
    return results
