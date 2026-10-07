"""Relógio e voz (CAD-227): comandos falados e aprovação pelo relógio, sem app próprio.

Cada pessoa cadastra o aparelho (Apple Watch/Siri, Wear OS, Alexa, Google) e recebe uma chave pessoal. O aparelho manda o
que a pessoa falou para ``/api/v1/publico/voz/<chave>/`` e recebe de volta uma frase curta para o relógio mostrar ou falar.

Comandos (português, com ou sem acento):
- "pendências" / "o que preciso aprovar"  → até 3 envios aguardando aprovação, cada um com um CÓDIGO de 4 dígitos;
- "aprovar 4821" / "recusar 4821"         → decide aquele envio (só aparelho com permissão de aprovar + cargo que aprova);
- "agenda" / "o que tenho hoje"           → tarefas de hoje e prazos dos próximos 2 dias;
- "lembrete ligar para a Maria amanhã"    → cria a tarefa para a própria pessoa (hoje ou amanhã);
- a frase de uma regra com gatilho "Atalho" ("cheguei ao fórum") → dispara a regra; o resto do que foi dito vira {{atalho.texto}};
- "ajuda"                                  → lista o que dá para dizer.

Segurança:
- a chave tem 256 bits, aparece uma vez e o banco guarda só o hash; revogar apaga o acesso na hora;
- aprovar exige o CÓDIGO do envio (ninguém aprova "o último" sem saber o que é);
- avisos no relógio (ntfy) levam só o nome da regra e o código — nunca nome de cliente nem texto da mensagem;
- tudo vai para a auditoria (sem o texto falado).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from datetime import datetime, time, timedelta

import requests
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils import timezone

from audit import service as audit
from automations.models import PersonalDevice, Rule, RuleRun

logger = logging.getLogger(__name__)

RATE_PER_MINUTE = 20
APPROVER_ROLES = {'OWNER', 'ADMIN', 'MEMBER'}
DECISION_SALT = 'cadrius.watch.decision'
DECISION_MAX_AGE = 24 * 3600
NUMBERS = {'zero': '0', 'um': '1', 'uma': '1', 'dois': '2', 'duas': '2', 'tres': '3', 'quatro': '4', 'cinco': '5', 'seis': '6',
           'meia': '6', 'sete': '7', 'oito': '8', 'nove': '9'}
HELP = ('Diga: "pendências", "aprovar" e o código, "recusar" e o código, "agenda de hoje", '
        '"lembrete" e o que lembrar, ou a frase de um atalho do escritório.')


class VoiceError(Exception):
    pass


# ----------------------------------------------------------------------------- chaves dos aparelhos
def _hash(key: str) -> str:
    return hashlib.sha256((key or '').encode()).hexdigest()


def create_device(org, user, *, name: str, kind: str, can_approve: bool, notify: bool) -> tuple[PersonalDevice, str]:
    key = 'cdv_' + secrets.token_urlsafe(32)
    device = PersonalDevice.objects.create(
        organization=org, user=user, name=(name or 'Meu relógio').strip()[:60],
        kind=kind if kind in PersonalDevice.Kind.values else PersonalDevice.Kind.APPLE,
        key_hash=_hash(key), can_approve=bool(can_approve), notify=bool(notify),
        ntfy_topic=f'cadrius-{secrets.token_urlsafe(18)}' if notify else '')
    audit.log('device.created', actor=user, organization=org, target=device,
              changes={'tipo': device.kind, 'aprova': device.can_approve, 'avisos': device.notify})
    return device, key


def device_for(key: str) -> PersonalDevice | None:
    if not key or not key.startswith('cdv_'):
        return None
    d = PersonalDevice.objects.filter(key_hash=_hash(key), revoked_at__isnull=True).select_related('user', 'organization').first()
    if d is None or not d.organization.is_active or not d.user.is_active:
        return None
    if not d.user.memberships.filter(organization=d.organization, is_active=True).exists():
        return None                                           # saiu do escritório: o aparelho para de funcionar
    return d


def throttled(device) -> bool:
    k = f'voz:{device.pk}:{timezone.now():%Y%m%d%H%M}'
    n = cache.get_or_set(k, 0, 70)
    if n >= RATE_PER_MINUTE:
        return True
    try:
        cache.incr(k)
    except ValueError:
        cache.set(k, 1, 70)
    return False


def _role(device) -> str:
    m = device.user.memberships.filter(organization=device.organization, is_active=True).first()
    return m.role if m else ''


def may_approve(device) -> bool:
    return device.can_approve and _role(device) in APPROVER_ROLES


# ----------------------------------------------------------------------------- código de aprovação
def code_for(run) -> str:
    """4 dígitos estáveis por execução (derivados da SECRET_KEY): o que a pessoa fala para aprovar."""
    digest = hmac.new(settings.SECRET_KEY.encode(), f'run:{run.pk}'.encode(), hashlib.sha256).hexdigest()
    return str(1000 + int(digest[:8], 16) % 9000)


def pending_runs(org):
    return list(RuleRun.objects.filter(organization=org, status=RuleRun.Status.PENDING).select_related('rule').order_by('created_at')[:100])


def run_by_code(org, code: str):
    hits = [r for r in pending_runs(org) if code_for(r) == code]
    if len(hits) != 1:
        return None
    return hits[0]


def _describe(run) -> str:
    """Resumo falável SEM dado de cliente: o que a regra faz e por qual canal."""
    kinds = {s.get('tipo') for s in run.steps or [] if s.get('status') == 'aguardando'}
    what = 'mensagem ao cliente' if kinds & {'send_whatsapp', 'send_email', 'send_message', 'send_survey'} else 'ação externa'
    return f'{what} da regra "{run.rule.name}"'


# ----------------------------------------------------------------------------- interpretação
def normalize(text: str) -> str:
    t = unicodedata.normalize('NFKD', (text or '').lower())
    t = ''.join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r'[^\w\s]', ' ', t)
    words = [NUMBERS.get(w, w) for w in t.split()]
    out = ' '.join(words)
    return re.sub(r'(?<=\d) (?=\d)', '', out)              # "4 8 2 1" → "4821"


def _shortcut_match(org, norm: str):
    """Regra de atalho cuja frase aparece no que foi dito. Devolve (regra, resto do texto) ou (None, '')."""
    best = None
    for rule in Rule.objects.filter(organization=org, trigger=Rule.Trigger.SHORTCUT, enabled=True):
        for phrase in (rule.trigger_config or {}).get('frases', []) or [rule.name]:
            p = normalize(phrase)
            if p and p in norm and (best is None or len(p) > len(best[1])):
                best = (rule, p)
    if best is None:
        return None, ''
    rest = norm.replace(best[1], ' ', 1).strip()
    return best[0], rest


def handle(device, text: str, *, dry_run: bool = False) -> dict:
    """Interpreta e executa. Devolve {'ok', 'acao', 'fala'} — 'fala' cabe na tela do relógio (até ~300 caracteres)."""
    norm = normalize(text)
    org, user = device.organization, device.user
    if not norm:
        return {'ok': False, 'acao': 'vazio', 'fala': f'Não ouvi nada. {HELP}'}

    m = re.search(r'\b(aprovar|aprove|aprova|recusar|recuse|recusa|rejeitar|rejeite|negar|negue)\b(?:\D*(\d{4})\b)?', norm)
    if m and (m.group(2) or norm.startswith(m.group(1))):
        approve = m.group(1).startswith('aprova')
        if m.group(2) is None:
            return {'ok': False, 'acao': 'codigo', 'fala': 'Diga o código de 4 dígitos do envio. Peça "pendências" para ouvir os códigos.'}
        if not may_approve(device):
            return {'ok': False, 'acao': 'sem_permissao',
                    'fala': 'Este aparelho não pode aprovar. Libere em Cadrius → Relógio e voz (o seu cargo precisa aprovar envios).'}
        run = run_by_code(org, m.group(2))
        if run is None:
            return {'ok': False, 'acao': 'codigo', 'fala': f'Não achei envio pendente com o código {m.group(2)}. Peça "pendências".'}
        if dry_run:
            return {'ok': True, 'acao': 'aprovar' if approve else 'recusar', 'fala': f'(teste) {"Aprovaria" if approve else "Recusaria"} {_describe(run)}.'}
        from automations import engine
        try:
            if approve:
                engine.approve(run, user)
            else:
                engine.reject(run, user, 'Recusado pelo relógio')
        except engine.DecisionError as exc:
            return {'ok': False, 'acao': 'aprovar' if approve else 'recusar', 'fala': str(exc)}
        audit.log('device.decision', actor=user, organization=org, target=run.rule,
                  changes={'execucao': run.pk, 'decisao': 'aprovada' if approve else 'recusada', 'aparelho': device.pk})
        return {'ok': True, 'acao': 'aprovar' if approve else 'recusar',
                'fala': f'{"Aprovado" if approve else "Recusado"}: {_describe(run)}.'}

    if re.search(r'\b(pendenc\w*|aprovac\w*|aguardando|aprovar)\b', norm):
        runs = pending_runs(org)
        if not runs:
            return {'ok': True, 'acao': 'pendencias', 'fala': 'Nada aguardando aprovação.'}
        items = '; '.join(f'código {code_for(r)}: {_describe(r)}' for r in runs[:3])
        more = f' E mais {len(runs) - 3} no Cadrius.' if len(runs) > 3 else ''
        tail = ' Diga "aprovar" ou "recusar" e o código.' if may_approve(device) else ''
        return {'ok': True, 'acao': 'pendencias', 'fala': f'{len(runs)} aguardando: {items}.{more}{tail}'[:400]}

    if re.search(r'\b(lembrete|lembre|lembrar|anota\w*|tarefa)\b', norm):
        tomorrow = bool(re.search(r'\bamanha\b', norm))
        title = re.sub(r'^\s*(ok\s+|cadrius[,\s]+)?(lembrete|lembre-me|lembre me|lembre|lembrar|anota a[ií]|anotar|anota|criar tarefa|nova tarefa|tarefa)'
                       r'\s*(de|para|que|:)?\s*', '', text.strip(), flags=re.I)
        title = re.sub(r'\bamanh[ãa]\b', '', title, flags=re.I).strip(' ,.:;')
        if len(title) < 3:
            return {'ok': False, 'acao': 'tarefa', 'fala': 'Diga o que lembrar, por exemplo: "lembrete ligar para a Maria amanhã".'}
        title = title[0].upper() + title[1:200]
        when = _when(tomorrow)
        if dry_run:
            return {'ok': True, 'acao': 'tarefa', 'fala': f'(teste) Criaria a tarefa "{title}" para {when:%d/%m às %Hh}.'}
        from tasks.models import UserTask
        UserTask.objects.create(titulo=title[:255], descricao='Criada por voz (Cadrius no relógio).', responsavel=user,
                                scheduled_at=when, priority='media')
        audit.log('device.command', actor=user, organization=org, changes={'acao': 'tarefa', 'aparelho': device.pk})
        return {'ok': True, 'acao': 'tarefa', 'fala': f'Anotado para {when:%d/%m às %Hh}: {title}.'}

    rule, rest = _shortcut_match(org, norm)
    if rule is not None:
        if dry_run:
            return {'ok': True, 'acao': 'atalho', 'fala': f'(teste) Rodaria o atalho "{rule.name}".'}
        from automations import shortcuts
        shortcuts.fire(rule, rest or '', 'voz')
        audit.log('automation.shortcut_fired', actor=user, organization=org, target=rule, changes={'via': 'voz', 'aparelho': device.pk})
        return {'ok': True, 'acao': 'atalho', 'fala': f'Feito: {rule.name}.'}

    if re.search(r'\b(agenda|hoje|compromisso\w*|prazo\w*|tarefas?)\b', norm):
        return {'ok': True, 'acao': 'agenda', 'fala': _agenda(device)}

    if re.search(r'\b(ajuda|o que voce faz|comandos)\b', norm):
        return {'ok': True, 'acao': 'ajuda', 'fala': HELP}
    return {'ok': False, 'acao': 'nao_entendi', 'fala': f'Não entendi. {HELP}'}


def _when(tomorrow: bool) -> datetime:
    now = timezone.localtime()
    if tomorrow:
        return timezone.make_aware(datetime.combine(now.date() + timedelta(days=1), time(9, 0)))
    nxt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return nxt if nxt.hour < 20 else timezone.make_aware(datetime.combine(now.date() + timedelta(days=1), time(9, 0)))


def _agenda(device) -> str:
    from publications.models import Publication
    from tasks.models import UserTask
    today = timezone.localdate()
    tasks = list(UserTask.objects.filter(responsavel=device.user, completed=False, scheduled_at__date=today).order_by('scheduled_at')[:3])
    n_tasks = UserTask.objects.filter(responsavel=device.user, completed=False, scheduled_at__date=today).count()
    prazos = Publication.objects.filter(organization=device.organization, vencimento__gte=today,
                                        vencimento__lte=today + timedelta(days=2)).exclude(status='descartada').count()
    if not n_tasks and not prazos:
        return 'Hoje está livre: nenhuma tarefa e nenhum prazo nos próximos 2 dias.'
    parts = [f'{n_tasks} tarefa(s) hoje' + (': ' + '; '.join(f'{timezone.localtime(t.scheduled_at):%Hh%M} {t.titulo[:50]}' for t in tasks) if tasks else '')]
    if prazos:
        parts.append(f'{prazos} prazo(s) até {today + timedelta(days=2):%d/%m}')
    return ('. '.join(parts) + '.')[:400]


# ----------------------------------------------------------------------------- avisos no relógio (ntfy)
def decision_token(run, device, decision: str) -> str:
    return signing.dumps({'r': run.pk, 'd': device.pk, 'x': decision}, salt=DECISION_SALT, compress=True)


def read_decision_token(token: str) -> dict:
    return signing.loads(token, salt=DECISION_SALT, max_age=DECISION_MAX_AGE)


def _public(path: str) -> str:
    return f'{(getattr(settings, "API_PUBLIC_URL", "") or "").rstrip("/")}{path}'


def notify_pending(run) -> int:
    """Avisa os aparelhos (com avisos ligados e permissão de aprovar) que há envio aguardando. Devolve quantos avisou."""
    base = (getattr(settings, 'NTFY_BASE_URL', '') or 'https://ntfy.sh').rstrip('/')
    sent = 0
    for d in PersonalDevice.objects.filter(organization=run.organization, notify=True, revoked_at__isnull=True).select_related('user'):
        if not d.ntfy_topic or not may_approve(d):
            continue
        code = code_for(run)
        actions = '; '.join([
            f'http, Aprovar, {_public("/api/v1/publico/relogio/decidir/" + decision_token(run, d, "aprovar") + "/")}, method=POST, clear=true',
            f'http, Recusar, {_public("/api/v1/publico/relogio/decidir/" + decision_token(run, d, "recusar") + "/")}, method=POST, clear=true',
        ])
        try:
            requests.post(f'{base}/{d.ntfy_topic}', timeout=5, data=f'{_describe(run).capitalize()}. Código {code}.'.encode(),
                          headers={'Title': 'Cadrius: aprovação pendente', 'Priority': 'high', 'Tags': 'scales',
                                   'Actions': actions})
            sent += 1
        except requests.RequestException as exc:
            logger.warning('Aviso ntfy falhou (aparelho %s): %s', d.pk, type(exc).__name__)
    return sent


def decide_by_token(token: str) -> dict:
    """Botão "Aprovar"/"Recusar" da notificação no relógio."""
    try:
        data = read_decision_token(token)
    except signing.SignatureExpired:
        return {'ok': False, 'fala': 'Este aviso expirou (24 h). Decida no Cadrius.'}
    except signing.BadSignature:
        return {'ok': False, 'fala': 'Aviso inválido.'}
    device = PersonalDevice.objects.filter(pk=data.get('d'), revoked_at__isnull=True).select_related('user', 'organization').first()
    run = RuleRun.objects.filter(pk=data.get('r')).select_related('rule', 'organization').first()
    if device is None or run is None or run.organization_id != device.organization_id or not may_approve(device):
        return {'ok': False, 'fala': 'Este aparelho não pode mais decidir este envio.'}
    return handle(device, f'{data.get("x")} {code_for(run)}')
