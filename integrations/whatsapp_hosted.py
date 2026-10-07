"""WhatsApp sem servidor próprio (CAD-225): o Cadrius hospeda a Evolution API e cada escritório conecta o número dele.

Fluxo para o escritório:
1. Informa o número (com DDD) e clica em "Conectar".
2. O Cadrius cria a instância do escritório e devolve o **QR code** (para ler de outro aparelho) e o **código de pareamento**
   (para digitar no próprio celular: WhatsApp → Aparelhos conectados → Conectar com número de telefone).
3. Se o celular do escritório não estiver por perto, o dono gera um **link** (vale 15 min) e manda para quem está com o celular;
   a página mostra o código e o passo a passo, sem login.
4. Quando a Evolution diz "open", o Cadrius cria a conexão WHATSAPP do escritório e as automações passam a enviar por ela.

O servidor Evolution do Cadrius é o mesmo de ``EVOLUTION_API_BASE_URL`` / ``EVOLUTION_API_GLOBAL_KEY`` (perfil ``whatsapp`` do
docker compose). A chave global nunca sai do servidor: a conexão do escritório guarda só o nome da instância.
"""
from __future__ import annotations

import logging
import re

import requests
from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)

TIMEOUT = 15
LINK_SALT = 'cadrius.whatsapp.link'
LINK_MAX_AGE = 15 * 60


class WhatsAppError(Exception):
    """Mensagem já pronta para a tela."""


def _base() -> str:
    return (getattr(settings, 'EVOLUTION_API_BASE_URL', '') or '').rstrip('/')


def _headers() -> dict:
    return {'apikey': getattr(settings, 'EVOLUTION_API_GLOBAL_KEY', '') or '', 'Content-Type': 'application/json'}


def instance_name(org) -> str:
    return f'cadrius-{str(org.pk).replace("-", "")[:16]}'


def normalize_number(raw: str) -> str:
    """Número brasileiro com DDD → 55DDNNNNNNNNN. Aceita com ou sem +55, espaços e traços."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) in (10, 11):
        digits = f'55{digits}'
    if not (digits.startswith('55') and len(digits) in (12, 13)):
        raise WhatsAppError('Informe o número com DDD, por exemplo (11) 98888-7777.')
    return digits


def _call(method: str, path: str, **kw):
    try:
        resp = requests.request(method, f'{_base()}{path}', headers=_headers(), timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        logger.warning('Evolution indisponível: %s', exc.__class__.__name__)
        raise WhatsAppError('O servidor de WhatsApp do Cadrius não respondeu. Tente em instantes ou fale com o suporte.') from exc
    try:
        data = resp.json()
    except ValueError:
        data = {}
    return resp.status_code, data


def available() -> bool:
    """O Cadrius está hospedando a Evolution neste ambiente?"""
    if not _base() or not getattr(settings, 'EVOLUTION_API_GLOBAL_KEY', ''):
        return False
    try:
        code, _ = _call('GET', '/')
    except WhatsAppError:
        return False
    return code < 500


def state(org) -> str:
    """'open' (conectado), 'connecting', 'close' ou 'inexistente'."""
    code, data = _call('GET', f'/instance/connectionState/{instance_name(org)}')
    if code == 404:
        return 'inexistente'
    return ((data.get('instance') or {}).get('state') or data.get('state') or 'close').lower()


def start(org, number: str) -> dict:
    """Cria a instância (se não existir) e pede QR code + código de pareamento para o número."""
    number = normalize_number(number)
    name = instance_name(org)
    if state(org) == 'inexistente':
        code, data = _call('POST', '/instance/create', json={'instanceName': name, 'integration': 'WHATSAPP-BAILEYS',
                                                             'qrcode': True, 'number': number})
        if code >= 400:
            logger.warning('Evolution recusou criar a instância (%s)', code)
            raise WhatsAppError('Não foi possível preparar o WhatsApp do escritório agora. Tente de novo em instantes.')
    code, data = _call('GET', f'/instance/connect/{name}', params={'number': number})
    if code >= 400:
        raise WhatsAppError('Não foi possível gerar o código de conexão. Tente de novo em instantes.')
    if (data.get('instance') or {}).get('state') == 'open':
        return {'estado': 'open'}
    return {'estado': 'connecting', 'qrcode': data.get('base64') or '', 'codigo_pareamento': data.get('pairingCode') or '',
            'numero_final': number[-4:]}


def disconnect(org) -> None:
    name = instance_name(org)
    _call('DELETE', f'/instance/logout/{name}')
    _call('DELETE', f'/instance/delete/{name}')


def ensure_connection(org, user):
    """Com a instância conectada, cria/ativa a conexão WHATSAPP do escritório (usada pelas automações)."""
    from integrations.models import AppConnection
    candidates = AppConnection.objects.filter(app_name='WHATSAPP', user__memberships__organization=org).order_by('-pk')
    conn = next((c for c in candidates if (c.credentials or {}).get('hosted')), None)
    if conn is None:
        conn = AppConnection(user=user, app_name='WHATSAPP', name='WhatsApp do escritório (Cadrius)')
    conn.credentials = {'hosted': True, 'instance_name': instance_name(org)}
    conn.is_active = True
    conn.save()
    return conn


def deactivate_connection(org) -> None:
    from integrations.models import AppConnection
    for c in AppConnection.objects.filter(app_name='WHATSAPP', user__memberships__organization=org):
        if (c.credentials or {}).get('hosted'):
            c.is_active = False
            c.save(update_fields=['is_active'])


# ----------------------------------------------------------------------------- link para quem está com o celular
def make_link_token(org, number: str, user) -> str:
    return signing.dumps({'o': str(org.pk), 'n': normalize_number(number), 'u': str(user.pk)}, salt=LINK_SALT)


def read_link_token(token: str) -> dict:
    try:
        return signing.loads(token, salt=LINK_SALT, max_age=LINK_MAX_AGE)
    except signing.SignatureExpired as exc:
        raise WhatsAppError('Este link expirou. Peça um novo ao escritório.') from exc
    except signing.BadSignature as exc:
        raise WhatsAppError('Link inválido.') from exc
