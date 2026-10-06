"""Clientes das integrações novas (CAD-174) e o "testar conexão" de cada app.

Hosts fixos dos provedores (ZapSign, Asaas, Meta, Telegram, Trello, ClickUp); hosts informados pelo escritório (SMTP, Evolution)
passam pela proteção contra SSRF. Nenhuma credencial vai para log ou resposta. **[VALIDAR]** os contratos marcados em cada função
contra a documentação vigente antes de usar com clientes reais (sandbox primeiro).
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import re
import socket
from urllib.parse import quote

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


def asaas_invoice(creds, *, payment_id, value, description, effective_date, service_code='', service_name='', iss_pct=0) -> dict:
    """Agenda a NFS-e de uma cobrança no Asaas (CAD-223). O escritório precisa ter a emissão de notas configurada no Asaas
    (prefeitura, certificado e serviço municipal). Devolve {'id', 'status', 'pdf'}."""
    body = {'payment': payment_id, 'serviceDescription': description[:500], 'observations': 'Emitida pelo Cadrius.',
            'value': float(value), 'deductions': 0, 'effectiveDate': effective_date.isoformat(),
            'taxes': {'retainIss': False, 'iss': float(iss_pct or 0), 'cofins': 0, 'csll': 0, 'inss': 0, 'ir': 0, 'pis': 0}}
    if service_code:
        body['municipalServiceCode'] = service_code[:20]
    if service_name:
        body['municipalServiceName'] = service_name[:120]
    inv = _asaas(creds, 'POST', '/invoices', json=body)
    return {'id': inv.get('id', ''), 'status': inv.get('status', ''), 'pdf': inv.get('pdfUrl') or ''}


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
    if app == 'D4SIGN':
        base = 'https://sandbox.d4sign.com.br' if is_yes(c.get('sandbox')) else 'https://secure.d4sign.com.br'
        _get(f'{base}/api/v1/account/balance', 'D4Sign', params={'tokenAPI': c.get('token_api'), 'cryptKey': c.get('crypt_key')})
        return 'Credenciais do D4Sign aceitas' + (' (sandbox).' if is_yes(c.get('sandbox')) else '.')
    if app == 'ESCAVADOR':
        _get('https://api.escavador.com/api/v1/quantidade-creditos', 'Escavador',
             headers={'Authorization': f'Bearer {c.get("token")}', 'X-Requested-With': 'XMLHttpRequest'})
        return 'Token do Escavador aceito.'
    if app == 'NOTION':
        data = _get('https://api.notion.com/v1/users/me', 'Notion',
                    headers={'Authorization': f'Bearer {c.get("token")}', 'Notion-Version': '2022-06-28'})
        return f'Integração "{data.get("name") or "Notion"}" conectada.'
    if app == 'PIPEDRIVE':
        data = _get('https://api.pipedrive.com/v1/users/me', 'Pipedrive', params={'api_token': c.get('api_token')})
        return f'Conectado como {(data.get("data") or {}).get("name", "?")}.'
    if app == 'CALENDLY':
        data = _get('https://api.calendly.com/users/me', 'Calendly', headers={'Authorization': f'Bearer {c.get("token")}'})
        return f'Conectado como {(data.get("resource") or {}).get("name", "?")}.'
    if app in ('SLACK', 'TEAMS'):
        post_team_message(conn, 'Teste do Cadrius: a conexão com o canal da equipe está funcionando.')
        return 'Mensagem de teste enviada ao canal.'
    # CAD-223 — chamadas só de leitura
    if app == 'BREVO':
        data = _get('https://api.brevo.com/v3/account', 'Brevo', headers={'api-key': str(c.get('api_key') or ''), 'accept': 'application/json'})
        return f'Conta Brevo de {data.get("companyName") or data.get("email") or "?"} conectada.'
    if app == 'MAILCHIMP':
        key = str(c.get('api_key') or '')
        dc = key.rsplit('-', 1)[-1] if '-' in key else ''
        if not re.fullmatch(r'us\d{1,3}', dc):
            raise IntegrationError('A chave do Mailchimp termina com o data center (ex.: -us21).')
        _get(f'https://{dc}.api.mailchimp.com/3.0/ping', 'Mailchimp', auth=('cadrius', key))
        return 'Chave do Mailchimp aceita.'
    if app == 'NFEIO':
        data = _get(f'https://api.nfe.io/v1/companies/{quote(str(c.get("company_id") or ""), safe="")}', 'NFE.io',
                    headers={'Authorization': str(c.get('api_key') or '')})
        company = data.get('companies') or data
        return f'Empresa {company.get("name") or company.get("federalTaxNumber") or "?"} encontrada na NFE.io.'
    if app == 'AUTENTIQUE':
        try:
            resp = requests.post('https://api.autentique.com.br/v2/graphql', timeout=TIMEOUT, json={'query': '{ me { name email } }'},
                                 headers={'Authorization': f'Bearer {c.get("token")}'})
        except requests.RequestException as exc:
            raise IntegrationError(f'Autentique inacessível ({exc.__class__.__name__}).') from exc
        data = _check(resp, 'Autentique')
        if data.get('errors'):
            raise IntegrationError('Autentique recusou o token.')
        return f'Conectado como {((data.get("data") or {}).get("me") or {}).get("name", "?")}.'
    if app == 'OMIE':
        try:
            resp = requests.post('https://app.omie.com.br/api/v1/geral/empresas/', timeout=TIMEOUT,
                                 json={'call': 'ListarEmpresas', 'app_key': str(c.get('app_key') or ''),
                                       'app_secret': str(c.get('app_secret') or ''), 'param': [{'pagina': 1, 'registros_por_pagina': 1}]})
        except requests.RequestException as exc:
            raise IntegrationError(f'Omie inacessível ({exc.__class__.__name__}).') from exc
        data = _check(resp, 'Omie')
        if data.get('faultstring'):
            raise IntegrationError(f'Omie: {str(data["faultstring"])[:120]}')
        return 'Credenciais do Omie aceitas.'
    if app == 'ZOOM':
        try:
            resp = requests.post('https://zoom.us/oauth/token', timeout=TIMEOUT,
                                 params={'grant_type': 'account_credentials', 'account_id': str(c.get('account_id') or '')},
                                 auth=(str(c.get('client_id') or ''), str(c.get('client_secret') or '')))
        except requests.RequestException as exc:
            raise IntegrationError(f'Zoom inacessível ({exc.__class__.__name__}).') from exc
        token = _check(resp, 'Zoom').get('access_token')
        me = _get('https://api.zoom.us/v2/users/me', 'Zoom', headers={'Authorization': f'Bearer {token}'})
        return f'Zoom conectado ({me.get("email") or "?"}).'
    raise IntegrationError('Este app não tem teste automático. Use-o numa automação de teste.')


# ----------------------------------------------------------------------------- chat da equipe (CAD-221)
TEAM_HOSTS = {'SLACK': ('hooks.slack.com',),
              'TEAMS': ('.webhook.office.com', '.logic.azure.com', '.environment.api.powerplatform.com')}


def team_webhook_url(app: str, url: str) -> str:
    """Só aceita URL HTTPS dos domínios oficiais do Slack/Teams (evita usar a conexão para chamar outro endereço — SSRF)."""
    from urllib.parse import urlparse
    url = (url or '').strip()
    host = (urlparse(url).hostname or '').lower()
    allowed = TEAM_HOSTS.get(app, ())
    if not url.startswith('https://') or not any(host == h or (h.startswith('.') and host.endswith(h)) for h in allowed):
        raise IntegrationError(f'URL do webhook do {"Slack" if app == "SLACK" else "Teams"} inválida: use a URL gerada pelo próprio app.')
    try:
        validate_outbound_url(url)
    except UnsafeURLError as exc:
        raise IntegrationError(str(exc)) from exc
    return url


def post_team_message(conn, text: str) -> None:
    c, app = conn.credentials or {}, conn.app_name
    if app == 'TELEGRAM':
        resp = requests.post(f'https://api.telegram.org/bot{c.get("telegram_bot_token")}/sendMessage', timeout=TIMEOUT,
                             json={'chat_id': c.get('telegram_chat_id'), 'text': text[:4000]})
        _check(resp, 'Telegram')
        return
    url = team_webhook_url(app, c.get('webhook_url'))
    try:
        resp = requests.post(url, json={'text': text[:4000]}, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException as exc:
        raise IntegrationError(f'{app.title()} inacessível ({exc.__class__.__name__}).') from exc
    if resp.status_code >= 400:
        raise IntegrationError(f'{"Slack" if app == "SLACK" else "Teams"} respondeu {resp.status_code}.')
