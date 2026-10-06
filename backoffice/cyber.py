"""Cibersegurança e monitoramento (CAD-221) — tela da TI na Gestão Cadrius.

Junta num lugar: servidor (CPU, memória, disco, carga), banco, Redis, fila, ameaças (logins com falha, bloqueios, acessos
negados, IPs mais ativos), alertas de anomalia, acessos (MFA, sessões, privilégios), configuração de segurança, IA e IPs
bloqueados — com uma nota geral e a lista do que fazer primeiro. Nada de conteúdo pessoal: e-mails mascarados, sem segredos.
Cada bloco falha sozinho ("indisponível") sem derrubar a tela.
"""
from __future__ import annotations

import logging
import os
import platform
import socket
import time
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

FAILED_LOGIN = ('auth.login.failure', 'auth.mfa.failed')
DENIED = ('permission.denied', 'ratelimit.hit', 'webhook.invalid_token', 'auth.login.locked')
LIMITS = {'cpu': 85, 'mem': 85, 'disk': 85}


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 — um bloco quebrado vira "indisponível"
        logger.warning('Painel de cibersegurança: %s falhou (%s)', fn.__name__, type(exc).__name__)
        return {'indisponivel': True}


def _gb(n) -> float:
    return round(n / 1024 ** 3, 2)


# ----------------------------------------------------------------------------- servidor
def server() -> dict:
    import psutil
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    disks = []
    for label, path in (('sistema', '/'), ('arquivos (media)', str(getattr(settings, 'MEDIA_ROOT', '') or ''))):
        if path and os.path.exists(path):
            d = psutil.disk_usage(path)
            disks.append({'nome': label, 'total_gb': _gb(d.total), 'usado_gb': _gb(d.used), 'pct': d.percent})
    load = os.getloadavg() if hasattr(os, 'getloadavg') else (0, 0, 0)
    proc = psutil.Process()
    net = psutil.net_io_counters()
    cpus = psutil.cpu_count() or 1
    return {
        'host': socket.gethostname(), 'sistema': f'{platform.system()} {platform.release()}',
        'python': platform.python_version(), 'django': __import__('django').get_version(),
        'cpu_pct': psutil.cpu_percent(interval=0.2), 'cpus': cpus,
        'carga': [round(x, 2) for x in load], 'carga_por_cpu': round(load[0] / cpus, 2),
        'memoria': {'total_gb': _gb(vm.total), 'usado_gb': _gb(vm.total - vm.available), 'pct': vm.percent},
        'swap_pct': sw.percent, 'discos': disks,
        'ligado_ha_horas': round((time.time() - psutil.boot_time()) / 3600, 1),
        'processos': len(psutil.pids()),
        'app': {'memoria_mb': round(proc.memory_info().rss / 1024 ** 2, 1), 'threads': proc.num_threads(),
                'iniciado_ha_horas': round((time.time() - proc.create_time()) / 3600, 1)},
        'rede': {'enviado_gb': _gb(net.bytes_sent), 'recebido_gb': _gb(net.bytes_recv),
                 'erros': net.errin + net.errout, 'descartes': net.dropin + net.dropout},
    }


def database() -> dict:
    started = time.monotonic()
    with connection.cursor() as cur:
        cur.execute('SELECT 1')
        latency = round((time.monotonic() - started) * 1000, 1)
        if connection.vendor != 'postgresql':
            return {'tipo': connection.vendor, 'latencia_ms': latency}
        cur.execute('SHOW server_version')
        version = cur.fetchone()[0]
        cur.execute('SELECT pg_database_size(current_database())')
        size = cur.fetchone()[0]
        cur.execute("SELECT state, count(*) FROM pg_stat_activity WHERE datname = current_database() GROUP BY state")
        states = {str(s or 'outro'): n for s, n in cur.fetchall()}
        cur.execute('SHOW max_connections')
        max_conn = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'active' "
                    "AND now() - query_start > interval '60 seconds'")
        slow = cur.fetchone()[0]
        cur.execute('SELECT blks_hit, blks_read, deadlocks, xact_commit, xact_rollback FROM pg_stat_database '
                    'WHERE datname = current_database()')
        hit, read, deadlocks, commits, rollbacks = cur.fetchone()
    total = sum(states.values())
    return {'tipo': 'postgresql', 'versao': version, 'latencia_ms': latency, 'tamanho_gb': _gb(size),
            'conexoes': total, 'conexoes_max': max_conn, 'conexoes_pct': round(100 * total / max_conn, 1) if max_conn else 0,
            'por_estado': states, 'consultas_lentas': slow, 'deadlocks': deadlocks,
            'cache_acerto_pct': round(100 * hit / (hit + read), 2) if (hit + read) else 100.0,
            'rollback_pct': round(100 * rollbacks / (commits + rollbacks), 2) if (commits + rollbacks) else 0.0}


def redis_info() -> dict:
    from django_redis import get_redis_connection
    started = time.monotonic()
    info = get_redis_connection('default').info()
    hits, misses = info.get('keyspace_hits', 0), info.get('keyspace_misses', 0)
    return {'latencia_ms': round((time.monotonic() - started) * 1000, 1), 'versao': info.get('redis_version'),
            'memoria_mb': round(info.get('used_memory', 0) / 1024 ** 2, 1),
            'memoria_max_mb': round(info.get('maxmemory', 0) / 1024 ** 2, 1) or None,
            'clientes': info.get('connected_clients'), 'bloqueados': info.get('blocked_clients'),
            'comandos_por_s': info.get('instantaneous_ops_per_sec'), 'conexoes_rejeitadas': info.get('rejected_connections', 0),
            'acerto_cache_pct': round(100 * hits / (hits + misses), 1) if (hits + misses) else None,
            'ligado_ha_horas': round(info.get('uptime_in_seconds', 0) / 3600, 1)}


def queue() -> dict:
    from backoffice.services import queue_info
    q = queue_info()
    return {k: q[k] for k in ('fila', 'workers', 'falhas_24h', 'sucessos_24h')} | {
        'ultimas_falhas': [{'nome': f['nome'], 'quando': f['quando'], 'erro': f['erro'][:160]} for f in q['ultimas_falhas'][:5]]}


# ----------------------------------------------------------------------------- ameaças
def threats(now) -> dict:
    from audit.models import AuditEvent
    since = now - timedelta(hours=24)
    events = AuditEvent.objects.filter(occurred_at__gte=since)
    hours = [(now - timedelta(hours=h)).replace(minute=0, second=0, microsecond=0) for h in range(23, -1, -1)]
    buckets = {h: {'hora': timezone.localtime(h).strftime('%H:00'), 'falhas_login': 0, 'negados': 0, 'logins': 0} for h in hours}
    rows = events.filter(action__in=(*FAILED_LOGIN, *DENIED, 'auth.login.success')).values_list('occurred_at', 'action', 'ip')
    ip_fail, ip_denied = Counter(), Counter()
    for when, action, ip in rows:
        h = when.replace(minute=0, second=0, microsecond=0)
        key = 'falhas_login' if action in FAILED_LOGIN else 'negados' if action in DENIED else 'logins'
        if h in buckets:
            buckets[h][key] += 1
        if ip and action in FAILED_LOGIN:
            ip_fail[ip] += 1
        elif ip and action in DENIED:
            ip_denied[ip] += 1
    targeted = Counter(events.filter(action__in=FAILED_LOGIN).exclude(actor_label='').values_list('actor_label', flat=True))
    from audit.ipblock import match
    top_ips = [{'ip': ip, 'falhas_login': ip_fail[ip], 'negados': ip_denied[ip], 'bloqueado': bool(match(ip))}
               for ip, _ in (ip_fail + ip_denied).most_common(10)]
    totals = Counter(events.values_list('action', flat=True))
    week = AuditEvent.objects.filter(occurred_at__gte=now - timedelta(days=7), action__in=FAILED_LOGIN).count()
    return {
        'falhas_login_24h': sum(totals[a] for a in FAILED_LOGIN), 'falhas_login_7d': week,
        'logins_24h': totals['auth.login.success'] + totals['auth.sso.login'],
        'bloqueios_24h': totals['auth.login.locked'], 'negados_24h': totals['permission.denied'],
        'limite_de_taxa_24h': totals['ratelimit.hit'], 'webhooks_invalidos_24h': totals['webhook.invalid_token'],
        'acoes_admin_24h': totals['backoffice.action'] + totals['admin.change'] + totals['admin.delete'],
        'exportacoes_24h': totals['data.export'] + totals['audit.export'],
        'por_hora': list(buckets.values()), 'ips': top_ips,
        'contas_visadas': [{'conta': label, 'falhas': n} for label, n in targeted.most_common(8)],
        'contas_travadas': locked_accounts(),
    }


def locked_accounts() -> list:
    from axes.models import AccessAttempt
    from audit.redaction import mask_email
    limit = getattr(settings, 'AXES_FAILURE_LIMIT', 5)
    return [{'conta': mask_email(a.username or ''), 'ip': a.ip_address, 'falhas': a.failures_since_start, 'desde': a.attempt_time}
            for a in AccessAttempt.objects.filter(failures_since_start__gte=limit).order_by('-attempt_time')[:15]]


def alerts() -> dict:
    from audit.models import AnomalyAlert
    open_qs = AnomalyAlert.objects.filter(status__in=('open', 'ack'))
    by_sev = Counter(open_qs.values_list('severity', flat=True))
    return {'abertos': open_qs.count(), 'por_gravidade': {s: by_sev.get(s, 0) for s in ('critical', 'high', 'medium', 'low')},
            'recentes': [{'id': a.pk, 'regra': a.rule, 'gravidade': a.severity, 'status': a.status, 'resumo': a.summary,
                          'ip': a.ip, 'quando': a.created_at} for a in AnomalyAlert.objects.all()[:12]]}


# ----------------------------------------------------------------------------- acessos
def access(now) -> dict:
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

    from accounts import mfa
    from accounts.models import OrganizationMembership
    from audit.redaction import mask_email
    User = get_user_model()
    staff = list(User.objects.filter(is_staff=True, is_active=True))
    staff_no_mfa = [u for u in staff if not mfa.enabled(u)]
    managers = User.objects.filter(is_active=True, memberships__is_active=True, memberships__role__in=('OWNER', 'ADMIN')).distinct()
    managers_mfa = sum(1 for u in managers if mfa.enabled(u))
    total_managers = managers.count()
    sessions = OutstandingToken.objects.filter(expires_at__gt=now, blacklistedtoken__isnull=True)
    stale = User.objects.filter(is_active=True, last_login__lt=now - timedelta(days=90)).count()
    return {
        'usuarios_ativos': User.objects.filter(is_active=True).count(),
        'sessoes_ativas': sessions.count(), 'pessoas_com_sessao': sessions.values('user_id').distinct().count(),
        'equipe': len(staff), 'equipe_sem_mfa': [mask_email(u.email) for u in staff_no_mfa],
        'superusuarios': User.objects.filter(is_superuser=True, is_active=True).count(),
        'gestores': total_managers, 'gestores_com_mfa': managers_mfa,
        'mfa_gestores_pct': round(100 * managers_mfa / total_managers) if total_managers else 100,
        'troca_de_senha_pendente': User.objects.filter(is_active=True, must_change_password=True).count(),
        'sem_acesso_90_dias': stale,
        'escritorios_ativos': OrganizationMembership.objects.filter(is_active=True).values('organization').distinct().count(),
    }


def config() -> dict:
    from compliance import checks
    s = settings
    headers = [
        ('HTTPS obrigatório (SECURE_SSL_REDIRECT)', bool(getattr(s, 'SECURE_SSL_REDIRECT', False))),
        ('HSTS ativo', int(getattr(s, 'SECURE_HSTS_SECONDS', 0) or 0) >= 31536000),
        ('Cookie de sessão só por HTTPS', bool(getattr(s, 'SESSION_COOKIE_SECURE', False))),
        ('Cookie CSRF só por HTTPS', bool(getattr(s, 'CSRF_COOKIE_SECURE', False))),
        ('Proteção contra clickjacking (X-Frame-Options)', getattr(s, 'X_FRAME_OPTIONS', '') in ('DENY', 'SAMEORIGIN')),
        ('Bloqueio de MIME sniffing', bool(getattr(s, 'SECURE_CONTENT_TYPE_NOSNIFF', True))),
        ('DEBUG desligado', not s.DEBUG),
        ('CORS restrito (sem liberar todas as origens)', not getattr(s, 'CORS_ALLOW_ALL_ORIGINS', False)),
        ('Bloqueio por tentativas de login (Axes)', bool(getattr(s, 'AXES_ENABLED', True))),
        ('Monitoramento de erros (Sentry)', bool(getattr(s, 'SENTRY_DSN', '') or '')),
    ]
    results = _safe(checks.run_all)
    verifications = [] if isinstance(results, dict) and results.get('indisponivel') else [
        {'nome': n, 'titulo': checks.TITLES.get(n, n), 'status': r.status, 'detalhe': r.detail} for n, r in results.items()]
    return {'cabecalhos': [{'item': name, 'ok': ok} for name, ok in headers], 'verificacoes': verifications,
            'falhas': [v for v in verifications if v['status'] == 'fail']}


def ai() -> dict:
    from aigov import llm
    from aigov.guard import global_ai_enabled
    from aigov.models import AIActionLog
    since = timezone.now() - timedelta(hours=24)
    logs = AIActionLog.objects.filter(created_at__gte=since)
    return {'ligada': global_ai_enabled(), 'pedidos_24h': logs.filter(blocked=False).count(),
            'bloqueados_24h': logs.filter(blocked=True).count(), 'falhas_24h': logs.filter(blocked=False, success=False).count(),
            'provedores': [{k: p[k] for k in ('chave', 'nome', 'configurado', 'gratuito', 'treina_com_dados', 'local', 'regiao')}
                           for p in llm.catalog()]}


def chain() -> dict:
    from audit.verify import verify_chain
    r = verify_chain(limit=500)
    return {'integra': bool(r.get('ok')), 'verificados': r.get('checked', 0)}


def blocked_ips() -> list:
    from audit.models import BlockedIP
    now = timezone.now()
    return [{'id': b.pk, 'rede': b.network, 'motivo': b.reason, 'por': b.created_by, 'criado_em': b.created_at,
             'expira_em': b.expires_at, 'ativo': b.expires_at is None or b.expires_at > now, 'tentativas_barradas': b.hits,
             'ultima_tentativa': b.last_hit_at} for b in BlockedIP.objects.all()[:100]]


# ----------------------------------------------------------------------------- nota e prioridades
def score(data: dict) -> tuple[int, list[dict]]:
    """Nota 0–100 e a lista do que resolver primeiro (mais grave antes)."""
    issues = []

    def add(weight, level, text, where):
        issues.append({'peso': weight, 'nivel': level, 'texto': text, 'onde': where})

    srv, db, rd, al, ac, cf, th = (data.get(k) or {} for k in ('servidor', 'banco', 'redis', 'alertas', 'acessos', 'configuracao', 'ameacas'))
    if db.get('indisponivel'):
        add(30, 'critico', 'Banco de dados sem resposta.', 'servidor')
    if rd.get('indisponivel'):
        add(15, 'alto', 'Redis (cache e fila) sem resposta.', 'servidor')
    if not data.get('trilha', {}).get('integra', True):
        add(30, 'critico', 'A trilha de auditoria perdeu a integridade (possível adulteração).', 'acessos')
    sev = al.get('por_gravidade') or {}
    if sev.get('critical'):
        add(25, 'critico', f'{sev["critical"]} alerta(s) crítico(s) aberto(s).', 'ameacas')
    if sev.get('high'):
        add(12, 'alto', f'{sev["high"]} alerta(s) de gravidade alta aberto(s).', 'ameacas')
    if ac.get('equipe_sem_mfa'):
        add(12, 'alto', f'{len(ac["equipe_sem_mfa"])} pessoa(s) da equipe Cadrius sem verificação em duas etapas.', 'acessos')
    if ac.get('mfa_gestores_pct', 100) < 50:
        add(5, 'medio', f'Só {ac["mfa_gestores_pct"]}% dos donos/administradores de escritório usam verificação em duas etapas.', 'acessos')
    for f in cf.get('falhas', [])[:6]:
        add(6, 'alto', f'Verificação com falha: {f["titulo"]}.', 'configuracao')
    for h in cf.get('cabecalhos', []):
        if not h['ok']:
            add(3, 'medio', f'Configuração: {h["item"]} não está ativo.', 'configuracao')
    if not srv.get('indisponivel'):
        if srv.get('cpu_pct', 0) >= LIMITS['cpu']:
            add(8, 'alto', f'CPU em {srv["cpu_pct"]}%.', 'servidor')
        if srv.get('memoria', {}).get('pct', 0) >= LIMITS['mem']:
            add(8, 'alto', f'Memória em {srv["memoria"]["pct"]}%.', 'servidor')
        for d in srv.get('discos', []):
            if d['pct'] >= LIMITS['disk']:
                add(10, 'alto', f'Disco "{d["nome"]}" em {d["pct"]}%.', 'servidor')
    if db.get('conexoes_pct', 0) >= 80:
        add(8, 'alto', f'Banco com {db["conexoes_pct"]}% das conexões em uso.', 'servidor')
    if th.get('falhas_login_24h', 0) >= 50:
        add(6, 'medio', f'{th["falhas_login_24h"]} logins com falha nas últimas 24 h (possível ataque de senha).', 'ameacas')
    if (data.get('fila') or {}).get('falhas_24h'):
        add(4, 'medio', f'{data["fila"]["falhas_24h"]} tarefa(s) em segundo plano falharam nas últimas 24 h.', 'servidor')
    issues.sort(key=lambda i: -i['peso'])
    return max(0, 100 - sum(i['peso'] for i in issues)), [{k: v for k, v in i.items() if k != 'peso'} for i in issues]


def snapshot() -> dict:
    now = timezone.now()
    data = {
        'gerado_em': now,
        'servidor': _safe(server), 'banco': _safe(database), 'redis': _safe(redis_info), 'fila': _safe(queue),
        'ameacas': _safe(threats, now), 'alertas': _safe(alerts), 'acessos': _safe(access, now),
        'configuracao': _safe(config), 'ia': _safe(ai), 'trilha': _safe(chain), 'ips_bloqueados': _safe(blocked_ips),
    }
    data['nota'], data['prioridades'] = score(data)
    return data
