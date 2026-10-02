"""Detecção de atividade fora do padrão — inclusive de utilizadores AUTENTICADOS (conta comprometida/insider).

Regras determinísticas e explicáveis (cada alerta traz ``details`` com a evidência). Executadas
periodicamente (Django-Q, a cada 5 min) por ``run_detectors``. Idempotentes via ``dedupe_key``.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from audit import service
from audit.models import AnomalyAlert, AuditEvent

logger = logging.getLogger('audit')
Sev = AnomalyAlert.Severity

# Limiares (ajustáveis por settings.AUDIT_THRESHOLDS)
DEFAULTS = {
    'failures_before_success': 3,     # A6: falhas antes de um sucesso (credential stuffing)
    'read_burst': 100,                # A3: leituras em 10 min
    'export_burst': 3,                # A4: exports em 1 h
    'denied_burst': 10,               # A5: permission.denied em 10 min (enumeração/IDOR)
    'distinct_ips': 3,                # A10: IPs distintos em 15 min
    'invalid_webhook_burst': 20,      # A9
    'ai_burst': 50,                   # A12
    'baseline_min_events': 50,        # A2: histórico mínimo p/ baseline
    'baseline_hour_share': 0.01,      # A2: hora com <1% do histórico = incomum
    'new_ip_min_events': 20,          # A1: histórico mínimo p/ falar em "novo IP"
}


def threshold(name: str) -> int | float:
    return {**DEFAULTS, **getattr(settings, 'AUDIT_THRESHOLDS', {})}[name]


def _bucket(now, minutes: int) -> str:
    return (now - timedelta(minutes=now.minute % minutes, seconds=now.second,
                            microseconds=now.microsecond)).strftime('%Y%m%d%H%M')


def _raise_alert(rule, severity, summary, *, actor_id='', actor_label='', organization_id=None, ip=None,
                 details=None, bucket='') -> AnomalyAlert | None:
    key = f'{rule}:{actor_id or ip or "-"}:{bucket}'[:128]
    if AnomalyAlert.objects.filter(dedupe_key=key).exists():
        return None  # já alertado nesta janela
    try:
        with transaction.atomic():  # savepoint: uma corrida não pode quebrar a transação do chamador
            alert = AnomalyAlert.objects.create(
                rule=rule, severity=severity, summary=summary[:255], actor_id=actor_id,
                actor_label=actor_label, organization_id=organization_id, ip=ip,
                details=details or {}, dedupe_key=key,
            )
    except IntegrityError:
        return None
    service.log('anomaly.detected', actor_type='system', reason=f'{rule}: {summary}'[:255],
                changes={'rule': rule, 'severity': severity, 'alert_id': alert.pk})
    _notify(alert)
    return alert


def _notify(alert: AnomalyAlert) -> None:
    """Notificação imediata: log estruturado (Dozzle/Sentry) e, se configurado, e-mail à segurança."""
    level = logging.CRITICAL if alert.severity == Sev.CRITICAL else logging.WARNING
    logger.log(level, 'security_alert rule=%s severity=%s alert_id=%s actor_id=%s',
               alert.rule, alert.severity, alert.pk, alert.actor_id)
    recipients = getattr(settings, 'SECURITY_ALERT_EMAILS', [])
    if recipients and alert.severity in (Sev.HIGH, Sev.CRITICAL):
        try:
            from django.core.mail import send_mail
            send_mail(f'[Cadrius] Alerta de segurança {alert.severity}: {alert.rule}',
                      f'{alert.summary}\n\nAlerta #{alert.pk} — {alert.details}',
                      None, recipients, fail_silently=True)
        except Exception:  # noqa: BLE001
            logger.exception('falha ao notificar alerta %s', alert.pk)


def _window(now, minutes):
    return AuditEvent.objects.filter(occurred_at__gte=now - timedelta(minutes=minutes))


# --------------------------------------------------------------------------- regras
def detect_failures_then_success(now):
    """A6 — várias falhas de login seguidas de sucesso (credential stuffing/senha adivinhada)."""
    n = threshold('failures_before_success')
    events = list(_window(now, 15).filter(action__in=['auth.login.failure', 'auth.login.success'])
                  .order_by('seq').values('action', 'actor_label', 'actor_id', 'ip', 'organization_id'))
    failures: dict = defaultdict(int)
    for e in events:
        key = e['ip']
        if e['action'] == 'auth.login.failure':
            failures[key] += 1
        elif failures[key] >= n:
            _raise_alert('A6_FAILS_THEN_SUCCESS', Sev.HIGH,
                         f'{failures[key]} falhas de login seguidas de sucesso a partir do mesmo IP',
                         actor_id=e['actor_id'], actor_label=e['actor_label'], ip=e['ip'],
                         organization_id=e['organization_id'], details={'failures': failures[key]},
                         bucket=_bucket(now, 15))
            failures[key] = 0


def _burst(now, *, rule, actions, minutes, limit, severity, summary_fmt, group='actor_id'):
    rows = (_window(now, minutes).filter(action__in=actions).exclude(**{group: ''})
            .values(group, 'actor_label', 'organization_id').annotate(n=Count('seq')).filter(n__gte=limit))
    for r in rows:
        _raise_alert(rule, severity, summary_fmt.format(n=r['n'], minutes=minutes),
                     actor_id=r['actor_id'] if group == 'actor_id' else '', actor_label=r['actor_label'],
                     organization_id=r['organization_id'], details={'count': r['n'], 'window_min': minutes},
                     bucket=_bucket(now, minutes))


def detect_read_burst(now):
    """A3 — pico de leitura de dados por um utilizador."""
    _burst(now, rule='A3_READ_BURST', actions=['data.read', 'data.bulk_read'], minutes=10,
           limit=threshold('read_burst'), severity=Sev.HIGH,
           summary_fmt='{n} leituras de dados em {minutes} min (possível exfiltração)')


def detect_export_burst(now):
    """A4 — exports/downloads em massa."""
    _burst(now, rule='A4_EXPORT_BURST', actions=['data.export', 'data.download'], minutes=60,
           limit=threshold('export_burst'), severity=Sev.HIGH,
           summary_fmt='{n} exports/downloads em {minutes} min')


def detect_denied_burst(now):
    """A5 — muitos acessos negados: enumeração de IDs / tentativa de acesso entre escritórios."""
    _burst(now, rule='A5_ENUMERATION', actions=['permission.denied'], minutes=10,
           limit=threshold('denied_burst'), severity=Sev.CRITICAL,
           summary_fmt='{n} acessos negados em {minutes} min (enumeração/IDOR?)')


def detect_ai_burst(now):
    """A12 — volume anómalo de pedidos à IA por utilizador."""
    _burst(now, rule='A12_AI_BURST', actions=['ai.request'], minutes=10, limit=threshold('ai_burst'),
           severity=Sev.HIGH, summary_fmt='{n} pedidos à IA em {minutes} min')


def detect_invalid_webhook_burst(now):
    """A9 — tentativas repetidas com token de webhook inválido (varredura de tokens)."""
    rows = (_window(now, 10).filter(action='webhook.invalid_token').exclude(ip=None)
            .values('ip').annotate(n=Count('seq')).filter(n__gte=threshold('invalid_webhook_burst')))
    for r in rows:
        _raise_alert('A9_WEBHOOK_SCAN', Sev.MEDIUM, f"{r['n']} webhooks com token inválido do mesmo IP",
                     ip=r['ip'], details={'count': r['n']}, bucket=_bucket(now, 10))


def detect_privilege_escalation(now):
    """A7 — concessão de ADMIN/OWNER (a conta convidada ou o convite podem ser maliciosos)."""
    for e in _window(now, 10).filter(action__in=['member.invited', 'member.role_changed']):
        if (e.changes or {}).get('role') in ('OWNER', 'ADMIN'):
            _raise_alert('A7_PRIVILEGE_CHANGE', Sev.HIGH,
                         f"Cargo {(e.changes or {}).get('role')} concedido", actor_id=e.actor_id,
                         actor_label=e.actor_label, organization_id=e.organization_id, ip=e.ip,
                         details={'event_seq': e.seq}, bucket=f'seq{e.seq}')


def detect_multiple_ips(now):
    """A10 — a mesma conta activa em ≥3 IPs em 15 min."""
    rows = (_window(now, 15).exclude(actor_id='').exclude(ip=None).values('actor_id', 'actor_label', 'organization_id')
            .annotate(n=Count('ip', distinct=True)).filter(n__gte=threshold('distinct_ips')))
    for r in rows:
        _raise_alert('A10_MULTI_IP', Sev.MEDIUM, f"Conta ativa em {r['n']} IPs em 15 min",
                     actor_id=r['actor_id'], actor_label=r['actor_label'], organization_id=r['organization_id'],
                     details={'distinct_ips': r['n']}, bucket=_bucket(now, 15))


def detect_baseline_deviation(now):
    """A1/A2 — atividade em hora ou IP nunca vistos no histórico do próprio utilizador (baseline individual)."""
    recent = list(_window(now, 15).exclude(actor_id='').exclude(actor_type='anonymous')
                  .values('actor_id', 'actor_label', 'organization_id', 'ip', 'occurred_at'))
    by_actor = defaultdict(list)
    for e in recent:
        by_actor[e['actor_id']].append(e)

    tz = timezone.get_current_timezone()
    for actor_id, events in by_actor.items():
        history = AuditEvent.objects.filter(
            actor_id=actor_id, occurred_at__gte=now - timedelta(days=30), occurred_at__lt=now - timedelta(minutes=15),
        ).values_list('occurred_at', 'ip')
        history = list(history)
        if len(history) < threshold('baseline_min_events'):
            continue  # sem histórico suficiente: não há baseline fiável
        hours = Counter(timezone.localtime(t, tz).hour for t, _ in history)
        known_ips = {ip for _, ip in history if ip}
        last = events[-1]
        hour = timezone.localtime(last['occurred_at'], tz).hour
        if hours.get(hour, 0) / len(history) < threshold('baseline_hour_share'):
            _raise_alert('A2_OFF_HOURS', Sev.MEDIUM, f'Atividade às {hour:02d}h, hora incomum para este utilizador',
                         actor_id=actor_id, actor_label=last['actor_label'], organization_id=last['organization_id'],
                         ip=last['ip'], details={'hour': hour}, bucket=_bucket(now, 15))
        if last['ip'] and known_ips and last['ip'] not in known_ips:
            _raise_alert('A1_NEW_IP', Sev.MEDIUM, 'Atividade a partir de um IP nunca visto para este utilizador',
                         actor_id=actor_id, actor_label=last['actor_label'], organization_id=last['organization_id'],
                         ip=last['ip'], bucket=_bucket(now, 15))


def detect_admin_data_access(now):
    """A11 — staff do Django Admin a consultar dados de clientes (acesso privilegiado)."""
    sensitive = ('emails.', 'integrations.', 'workflows.', 'accounts.', 'tasks.')
    for e in _window(now, 10).filter(action='admin.access'):
        if e.target_type.startswith(sensitive):
            _raise_alert('A11_ADMIN_DATA_ACCESS', Sev.MEDIUM, f'Staff acedeu a {e.target_type} no Admin',
                         actor_id=e.actor_id, actor_label=e.actor_label, ip=e.ip,
                         details={'model': e.target_type}, bucket=f'seq{e.seq}')


DETECTORS = (
    detect_failures_then_success, detect_read_burst, detect_export_burst, detect_denied_burst,
    detect_ai_burst, detect_invalid_webhook_burst, detect_privilege_escalation, detect_multiple_ips,
    detect_baseline_deviation, detect_admin_data_access,
)


def run_detectors(now=None) -> int:
    """Executa todas as regras; devolve nº de alertas novos."""
    now = now or timezone.now()
    before = AnomalyAlert.objects.count()
    for detector in DETECTORS:
        try:
            detector(now)
        except Exception:  # noqa: BLE001 — uma regra com defeito não pode silenciar as outras
            logger.exception('detector %s falhou', detector.__name__)
    return AnomalyAlert.objects.count() - before
