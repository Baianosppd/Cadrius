"""Clientes das integrações novas (CAD-174) e o "testar conexão" de cada app.

Hosts fixos dos provedores (ZapSign, Asaas, Meta, Telegram, Trello, ClickUp); hosts informados pelo escritório (SMTP, Evolution)
passam pela proteção contra SSRF. Nenhuma credencial vai para log ou resposta. **[VALIDAR]** os contratos marcados em cada função
contra a documentação vigente antes de usar com clientes reais (sandbox primeiro).
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import socket

import requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.core.mail.backends.smtp import EmailBackend

from integrations.catalog import is_yes
from integrations.ssrf import UnsafeURLError, _is_forbidden_ip, validate_outbound_url

logger = logging.getLogger(__name__)
TIMEOUT = 15


class IntegrationError(Exception):
    pass


def org_connection(org, app):
    """Conexão ativa mais recente do app entre os membros ativos do escritório."""
    from integrations.models import AppConnection
    return (AppConnection.objects.filter(app_name=app, is_active=True, user__memberships__organization=org,
                                         user__memberships__is_active=True).order_by('-pk').first())


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        return {}


def _check(resp, what):
    if resp.status_code in (401, 403):
        raise IntegrationError(f'{what} recusou as credenciais ({resp.status_code}). Confira a chave/token.')
    if resp.status_code >= 400:
        detail = _json(resp)
        msg = ''
        if isinstance(detail, dict):
            errs = detail.get('errors') or detail.get('error') or detail.get('detail') or ''
            if isinstance(errs, list) and errs:
                msg = str(errs[0].get('description') if isinstance(errs[0], dict) else errs[0])
            elif isinstance(errs, dict):
                msg = str(errs.get('message') or '')
            else:
                msg = str(errs)
        raise IntegrationError(f'{what} respondeu {resp.status_code}{": " + msg[:200] if msg else ""}.')
    return _json(resp)


# ----------------------------------------------------------------------------- SMTP do escritório
def _safe_smtp_host(host: str) -> str:
    host = (host or '').strip()
    if not host or '/' in host or ' ' in host:
        raise IntegrationError('Servidor SMTP inválido.')
    if getattr(settings, 'OUTBOUND_ALLOW_PRIVATE_NETWORKS', False):
        return host
    try:
        infos = socket.getaddrinfo(host, 587, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise IntegrationError(f'Não foi possível encontrar o servidor {host}.') from exc
    if any(_is_forbidden_ip(ipaddress.ip_address(i[4][0])) for i in infos):
        raise IntegrationError('O servidor SMTP aponta para um endereço interno (não permitido).')
    return host


def smtp_backend(creds) -> EmailBackend:
    try:
        port = int(str(creds.get('port') or 587))
    except ValueError as exc:
        raise IntegrationError('Porta SMTP inválida.') from exc
    if port not in (25, 465, 587, 2525):
        raise IntegrationError('Porta SMTP deve ser 465, 587, 2525 ou 25.')
    return EmailBackend(host=_safe_smtp_host(creds.get('host')), port=port, username=creds.get('username'),
                        password=creds.get('password'), use_tls=port in (587, 2525, 25), use_ssl=port == 465,
                        timeout=TIMEOUT, fail_silently=False)


def send_office_email(org, subject, body, to: list) -> bool:
    """Envia pelo SMTP do escritório, se configurado. Devolve False quando não há SMTP (o chamador usa o remetente do Cadrius)."""
    conn = org_connection(org, 'SMTP')
    if conn is None:
        return False
    creds = conn.credentials or {}
    backend = smtp_backend(creds)
    sender = (creds.get('from_email') or creds.get('username') or settings.DEFAULT_FROM_EMAIL).strip()
    EmailMessage(subject, body, sender, to, connection=backend).send(fail_silently=False)
    return True


# ----------------------------------------------------------------------------- ZapSign
def _zapsign_base(creds):
    return 'https://sandbox.api.zapsign.com.br/api/v1' if is_yes(creds.get('sandbox')) else 'https://api.zapsign.com.br/api/v1'


def zapsign_send(creds, *, name: str, pdf: bytes, signers: list) -> dict:
    """Cria o documento e devolve {'token', 'signatarios': [{'nome', 'link', 'status'}]}. [VALIDAR] contrato no sandbox."""
    body = {'name': name[:250], 'base64_pdf': base64.b64encode(pdf).decode(), 'lang': 'pt-br', 'signers': [
        {'name': s['nome'][:200], 'email': s.get('email') or '', 'phone_country': '55', 'phone_number': s.get('telefone') or '',
         'send_automatic_email': bool(s.get('email')), 'send_automatic_whatsapp': False} for s in signers]}
    try:
        resp = requests.post(f'{_zapsign_base(creds)}/docs/', json=body, timeout=TIMEOUT,
                             headers={'Authorization': f'Bearer {creds.get("api_token")}'})
    except requests.RequestException as exc:
        raise IntegrationError(f'ZapSign inacessível ({exc.__class__.__name__}).') from exc
    data = _check(resp, 'ZapSign')
    return {'token': data.get('token', ''), 'status': data.get('status', ''),
            'signatarios': [{'nome': s.get('name', ''), 'link': s.get('sign_url', ''), 'status': s.get('status', '')}
                            for s in data.get('signers') or []]}


# ----------------------------------------------------------------------------- Asaas
def _asaas_base(creds):
    return 'https://api-sandbox.asaas.com/v3' if is_yes(creds.get('sandbox')) else 'https://api.asaas.com/v3'


def _asaas(creds, method, path, **kw):
    try:
        resp = requests.request(method, f'{_asaas_base(creds)}{path}', timeout=TIMEOUT,
                                headers={'access_token': str(creds.get('api_key') or ''), 'Content-Type': 'application/json',
                                         'User-Agent': 'Cadrius'}, **kw)
    except requests.RequestException as exc:
        raise IntegrationError(f'Asaas inacessível ({exc.__class__.__name__}).') from exc
    return _check(resp, 'Asaas')


def asaas_charge(creds, *, contact, value, due_date, description, billing_type='UNDEFINED') -> dict:
    """Garante o cliente no Asaas (pelo CPF/CNPJ) e cria a cobrança. Devolve {'id', 'link', 'boleto', 'status'}."""
    import re
    doc = re.sub(r'\D', '', contact.document or '')
    if len(doc) not in (11, 14):
        raise IntegrationError('O contato precisa de CPF ou CNPJ para gerar cobrança.')
    found = _asaas(creds, 'GET', '/customers', params={'cpfCnpj': doc}).get('data') or []
    if found:
        customer = found[0]['id']
    else:
        customer = _asaas(creds, 'POST', '/customers', json={'name': contact.name[:100], 'cpfCnpj': doc, 'email': contact.email or None,
                                                            'mobilePhone': re.sub(r'\D', '', contact.phone or '') or None})['id']
    pay = _asaas(creds, 'POST', '/payments', json={'customer': customer, 'billingType': billing_type, 'value': float(value),
                                                   'dueDate': due_date.isoformat(), 'description': description[:500]})
    return {'id': pay.get('id', ''), 'link': pay.get('invoiceUrl', ''), 'boleto': pay.get('bankSlipUrl', ''), 'status': pay.get('status', '')}


# ----------------------------------------------------------------------------- Meta (Facebook / Instagram)
def _graph():
    return f'https://graph.facebook.com/{getattr(settings, "META_GRAPH_VERSION", "v21.0")}'


def _meta(method, path, creds, **data):
    token = creds.get('page_access_token') or ''
    try:
        resp = requests.request(method, f'{_graph()}/{path}', timeout=TIMEOUT,
                                **({'params': {**data, 'access_token': token}} if method == 'GET' else {'data': {**data, 'access_token': token}}))
    except requests.RequestException as exc:
        raise IntegrationError(f'Meta inacessível ({exc.__class__.__name__}).') from exc
    return _check(resp, 'Meta')


def meta_publish(creds, channel: str, text: str, image_url: str = '', link: str = '') -> str:
    """Publica agora. Facebook: texto (+ link) ou foto; Instagram: exige imagem em URL pública. Devolve o id da publicação."""
    if channel == 'facebook':
        page = creds.get('page_id')
        if image_url:
            return str(_meta('POST', f'{page}/photos', creds, url=image_url, caption=text).get('post_id') or '')
        extra = {'link': link} if link else {}
        return str(_meta('POST', f'{page}/feed', creds, message=text, **extra).get('id') or '')
    if channel == 'instagram':
        ig = creds.get('ig_user_id')
        if not ig:
            raise IntegrationError('Informe o ID do Instagram profissional na conexão Meta.')
        if not image_url:
            raise IntegrationError('O Instagram exige uma imagem (URL pública) para publicar.')
        container = _meta('POST', f'{ig}/media', creds, image_url=image_url, caption=text).get('id')
        return str(_meta('POST', f'{ig}/media_publish', creds, creation_id=container).get('id') or '')
    raise IntegrationError('Canal sem publicação automática.')


# ----------------------------------------------------------------------------- testar conexão
def _get(url, what, **kw):
    try:
        resp = requests.get(url, timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise IntegrationError(f'{what} inacessível ({exc.__class__.__name__}).') from exc
    return _check(resp, what)


def test_connection(conn) -> str:
    """Faz uma chamada só de leitura e devolve uma frase de sucesso; levanta IntegrationError com o motivo."""
    c, app = conn.credentials or {}, conn.app_name
    if app == 'SMTP':
        backend = smtp_backend(c)
        try:
            backend.open()
        except Exception as exc:  # noqa: BLE001 — smtplib levanta vários tipos
            raise IntegrationError(f'Não foi possível entrar no SMTP ({exc.__class__.__name__}). Confira servidor, porta e senha de app.') from exc
        finally:
            backend.close()
        return 'Login no servidor de e-mail funcionou.'
    if app == 'ZAPSIGN':
        _get(f'{_zapsign_base(c)}/docs/', 'ZapSign', headers={'Authorization': f'Bearer {c.get("api_token")}'})
        return 'Token do ZapSign aceito.'
    if app == 'ASAAS':
        _asaas(c, 'GET', '/customers', params={'limit': 1})
        return 'Chave do Asaas aceita' + (' (sandbox).' if is_yes(c.get('sandbox')) else '.')
    if app == 'META':
        data = _meta('GET', str(c.get('page_id')), c, fields='name')
        return f'Página "{data.get("name", "")}" encontrada.'
    if app == 'TELEGRAM':
        data = _get(f'https://api.telegram.org/bot{c.get("telegram_bot_token")}/getMe', 'Telegram')
        return f'Bot @{(data.get("result") or {}).get("username", "?")} ativo.'
    if app == 'TRELLO':
        data = _get('https://api.trello.com/1/members/me', 'Trello', params={'key': c.get('trello_api_key'), 'token': c.get('trello_api_token')})
        return f'Conectado como {data.get("username", "?")}.'
    if app == 'CLICKUP':
        data = _get('https://api.clickup.com/api/v2/user', 'ClickUp', headers={'Authorization': str(c.get('token') or '')})
        return f'Conectado como {(data.get("user") or {}).get("username", "?")}.'
    if app == 'WHATSAPP':
        base = (c.get('base_url') or settings.EVOLUTION_API_BASE_URL).rstrip('/')
        if c.get('base_url'):
            try:
                validate_outbound_url(base)
            except UnsafeURLError as exc:
                raise IntegrationError(str(exc)) from exc
        data = _get(f'{base}/instance/connectionState/{c.get("instance_name")}', 'Evolution API', headers={'apikey': str(c.get('api_key') or '')})
        state = (data.get('instance') or {}).get('state') or data.get('state') or '?'
        return f'Instância encontrada (estado: {state}).'
    raise IntegrationError('Este app não tem teste automático. Use-o numa automação de teste.')
