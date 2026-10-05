"""Setor Fiscal da Cadrius — fase 2 (CAD-175): emissão da NFS-e das assinaturas/pacotes pelo emissor, com conferência antes.

Provedor: **Focus NFe** (API REST com token; cobre o padrão nacional e os municípios). Fluxo: *conferir* (monta a nota e aponta o
que falta) → *emitir* (envia com uma referência única = idempotente) → o emissor processa e o Cadrius consulta a situação
(comando ``fiscal_sync`` a cada 15 min ou botão "Atualizar") → autorizada (nº + link) ou erro (mensagem do emissor).
Cancelamento com justificativa (mín. 15 caracteres). Sem emissor configurado, o registro manual da fase 1 continua valendo.

[VALIDAR antes de produção] caminho do endpoint (``FOCUSNFE_NFSE_PATH``: ``nfse`` municipal ou ``nfsen`` padrão nacional), item da
lista de serviços/código de tributação do SaaS, alíquota do ISS e regime — tudo vem do .env (``CADRIUS_FISCAL_*``), nada fixo no código.
Reforma tributária: em 2026 a CBS (0,9%) e o IBS (0,1%) são informativos/teste; para o Simples o destaque é exigido só a partir de 2027.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings
from django.utils import timezone

from audit import service as audit
from backoffice.services import ActionError
from billing.models import Payment

TIMEOUT = 20
S = Payment.InvoiceStatus


def config() -> dict:
    g = lambda k, d='': getattr(settings, k, d)  # noqa: E731
    return {
        'provedor': g('FISCAL_NFSE_PROVIDER', 'manual'), 'base': g('FOCUSNFE_BASE', 'https://homologacao.focusnfe.com.br').rstrip('/'),
        'token': g('FOCUSNFE_TOKEN'), 'path': g('FOCUSNFE_NFSE_PATH', 'nfse'),
        'cnpj': g('CADRIUS_FISCAL_CNPJ'), 'inscricao_municipal': g('CADRIUS_FISCAL_IM'), 'codigo_municipio': g('CADRIUS_FISCAL_COD_MUNICIPIO'),
        'item_lista_servico': g('CADRIUS_FISCAL_ITEM_SERVICO'), 'codigo_tributario_municipio': g('CADRIUS_FISCAL_COD_TRIBUTARIO'),
        'aliquota_iss': Decimal(str(g('CADRIUS_FISCAL_ALIQUOTA_ISS', '0') or '0')), 'regime': g('CADRIUS_FISCAL_REGIME', 'simples'),
        'cbs_pct': Decimal(str(g('FISCAL_CBS_PCT', '0.9'))), 'ibs_pct': Decimal(str(g('FISCAL_IBS_PCT', '0.1'))),
        'retencoes': g('FISCAL_RETENCOES_PJ', {}) or {},
    }


def is_automatic() -> bool:
    c = config()
    return c['provedor'] == 'focusnfe' and bool(c['token'])


def _tomador(org) -> dict:
    owner = org.members.filter(role='OWNER', is_active=True).select_related('user').first()
    doc = ''.join(ch for ch in (org.cnpj or (owner.user.cpf if owner else '') or '') if ch.isdigit())
    t = {'razao_social': org.razao_social or str(org), 'email': owner.user.email if owner else ''}
    if len(doc) == 14:
        t['cnpj'] = doc
    elif len(doc) == 11:
        t['cpf'] = doc
    return t


def _cents(v: Decimal) -> str:
    return f'{v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)}'


def preview(payment: Payment) -> dict:
    """A nota que seria emitida + o que falta. Nada é enviado."""
    c = config()
    valor = Decimal(payment.amount_cents) / 100
    tom = _tomador(payment.organization)
    competencia = timezone.localtime(payment.paid_at).date()
    discriminacao = f'{payment.get_kind_display()} Cadrius — {payment.description or "serviço de software"} — competência {competencia:%m/%Y}'
    iss = valor * c['aliquota_iss'] / 100
    pj = 'cnpj' in tom
    retencoes = []
    if pj:
        for nome, pct in (c['retencoes'] or {}).items():
            retencoes.append({'tributo': nome, 'aliquota': str(pct), 'valor': _cents(valor * Decimal(str(pct)) / 100)})
    reforma = {'cbs': _cents(valor * c['cbs_pct'] / 100), 'ibs': _cents(valor * c['ibs_pct'] / 100),
               'cbs_pct': str(c['cbs_pct']), 'ibs_pct': str(c['ibs_pct']),
               'observacao': ('Simples Nacional: destaque de CBS/IBS obrigatório a partir de 2027; em 2026 os valores são só informativos.'
                              if c['regime'] == 'simples' and competencia.year < 2027 else
                              'Valores de teste da reforma (CBS/IBS) — conferir com o contador o preenchimento no layout vigente.')}
    faltando = []
    for key, label in (('cnpj', 'CNPJ da Cadrius'), ('inscricao_municipal', 'inscrição municipal'), ('codigo_municipio', 'código do município (IBGE)'),
                       ('item_lista_servico', 'item da lista de serviços')):
        if not c[key]:
            faltando.append(f'Configurar {label} (CADRIUS_FISCAL_*).')
    if not ('cnpj' in tom or 'cpf' in tom):
        faltando.append('O escritório (tomador) não tem CNPJ nem CPF do dono cadastrado.')
    if not c['aliquota_iss']:
        faltando.append('Configurar a alíquota do ISS (CADRIUS_FISCAL_ALIQUOTA_ISS).')
    nota = {
        'data_emissao': timezone.localtime().isoformat(timespec='seconds'),
        'prestador': {'cnpj': c['cnpj'], 'inscricao_municipal': c['inscricao_municipal'], 'codigo_municipio': c['codigo_municipio']},
        'tomador': tom,
        'servico': {'valor_servicos': _cents(valor), 'discriminacao': discriminacao[:2000], 'item_lista_servico': c['item_lista_servico'],
                    'codigo_tributario_municipio': c['codigo_tributario_municipio'], 'aliquota': str(c['aliquota_iss']),
                    'iss_retido': False, 'codigo_municipio': c['codigo_municipio']},
    }
    return {'nota': nota, 'iss': _cents(iss), 'retencoes': retencoes, 'tomador_pj': pj, 'reforma': reforma, 'faltando': faltando,
            'automatico': is_automatic(), 'situacao': payment.invoice_status}


def _request(method, url, **kw):
    c = config()
    try:
        return requests.request(method, url, auth=(c['token'], ''), timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise ActionError(f'Emissor inacessível ({exc.__class__.__name__}). Tente de novo em instantes.') from exc


def _url(ref=''):
    c = config()
    return f'{c["base"]}/v2/{c["path"]}' + (f'/{ref}' if ref else '')


def emit(actor, payment: Payment, reason: str) -> dict:
    if not is_automatic():
        raise ActionError('Emissor de NFS-e não configurado: registre a nota emitida manualmente (fase 1) ou configure o FOCUSNFE_TOKEN.')
    if payment.invoice_status in (S.ISSUED, S.PROCESSING):
        raise ActionError('Esta nota já foi emitida ou está em processamento.')
    pv = preview(payment)
    if pv['faltando']:
        raise ActionError('Antes de emitir: ' + ' '.join(pv['faltando']))
    ref = payment.nfse_ref or f'cadrius-{payment.pk}'
    if payment.invoice_status in (S.ERROR, S.CANCELED):
        ref = f'cadrius-{payment.pk}-{int(timezone.now().timestamp())}'    # nova tentativa = nova referência
    resp = _request('POST', _url(), params={'ref': ref}, json=pv['nota'])
    body = _json(resp)
    if resp.status_code >= 400 and resp.status_code != 422:
        raise ActionError(f'O emissor recusou ({resp.status_code}): {body.get("mensagem") or body.get("codigo") or "verifique os dados"}.')
    payment.nfse_ref, payment.nfse_error = ref, ''
    payment.invoice_status = S.PROCESSING
    if resp.status_code == 422 or body.get('status') == 'erro_autorizacao':
        payment.invoice_status, payment.nfse_error = S.ERROR, _errors(body)
    payment.save(update_fields=['nfse_ref', 'nfse_error', 'invoice_status'])
    audit.log('fiscal.nfse_requested', actor=actor, organization=payment.organization, target=payment, reason=reason[:255],
              changes={'ref': ref, 'valor_centavos': payment.amount_cents, 'situacao': payment.invoice_status},
              data_categories=['financeiro', 'identificacao'], legal_basis='obrigacao_legal')
    return refresh(payment) if payment.invoice_status == S.PROCESSING else row(payment)


def refresh(payment: Payment) -> dict:
    """Consulta a situação no emissor e atualiza (autorizado → emitida; erro → mensagem; cancelado)."""
    if not (is_automatic() and payment.nfse_ref) or payment.invoice_status not in (S.PROCESSING, S.ISSUED):
        return row(payment)
    resp = _request('GET', _url(payment.nfse_ref))
    body = _json(resp)
    st = body.get('status', '')
    if st == 'autorizado':
        was = payment.invoice_status
        payment.invoice_status = S.ISSUED
        payment.invoice_number = str(body.get('numero') or body.get('numero_nfse') or '')[:60]
        payment.invoice_issued_at = _date(body.get('data_emissao')) or timezone.localdate()
        payment.nfse_url = str(body.get('url') or body.get('url_danfse') or body.get('caminho_xml_nota_fiscal') or '')[:500]
        payment.save(update_fields=['invoice_status', 'invoice_number', 'invoice_issued_at', 'nfse_url'])
        if was != S.ISSUED:
            _send_to_client(payment)
    elif st == 'erro_autorizacao':
        payment.invoice_status, payment.nfse_error = S.ERROR, _errors(body)
        payment.save(update_fields=['invoice_status', 'nfse_error'])
    elif st == 'cancelado':
        payment.invoice_status = S.CANCELED
        payment.save(update_fields=['invoice_status'])
    return row(payment)


def cancel(actor, payment: Payment, justification: str) -> dict:
    justification = (justification or '').strip()
    if len(justification) < 15:
        raise ActionError('Justificativa do cancelamento com pelo menos 15 caracteres.')
    if payment.invoice_status != S.ISSUED:
        raise ActionError('Só notas emitidas podem ser canceladas.')
    if is_automatic() and payment.nfse_ref:
        resp = _request('DELETE', _url(payment.nfse_ref), json={'justificativa': justification[:255]})
        body = _json(resp)
        if resp.status_code >= 400 or body.get('status') not in ('cancelado', None, ''):
            raise ActionError(f'O emissor não cancelou: {_errors(body) or resp.status_code}.')
    payment.invoice_status, payment.invoice_note = S.CANCELED, f'Cancelada: {justification}'[:255]
    payment.save(update_fields=['invoice_status', 'invoice_note'])
    audit.log('fiscal.nfse_canceled', actor=actor, organization=payment.organization, target=payment, reason=justification[:255],
              changes={'ref': payment.nfse_ref, 'numero': payment.invoice_number}, legal_basis='obrigacao_legal')
    return row(payment)


def sync_processing() -> dict:
    out = {'consultadas': 0, 'emitidas': 0, 'erros': 0}
    if not is_automatic():
        return out
    for p in Payment.objects.filter(invoice_status=S.PROCESSING).select_related('organization')[:200]:
        out['consultadas'] += 1
        try:
            r = refresh(p)
        except ActionError:
            continue
        out['emitidas'] += r['nf_status'] == S.ISSUED
        out['erros'] += r['nf_status'] == S.ERROR
    return out


def row(payment: Payment) -> dict:
    from backoffice.fiscal import payment_row
    return {**payment_row(payment), 'nfse_ref': payment.nfse_ref, 'nfse_url': payment.nfse_url, 'nfse_erro': payment.nfse_error}


def _send_to_client(payment):
    tom = _tomador(payment.organization)
    if not tom.get('email') or not payment.nfse_url:
        return
    from django.core.mail import send_mail
    try:
        send_mail(f'Cadrius: nota fiscal nº {payment.invoice_number}',
                  f'Olá!\n\nA nota fiscal do pagamento "{payment.description or payment.get_kind_display()}" foi emitida:\n'
                  f'{payment.nfse_url}\n\nEquipe Cadrius', settings.DEFAULT_FROM_EMAIL, [tom['email']])
    except Exception:  # noqa: BLE001 — a nota está emitida; o envio pode ser refeito
        pass


def _json(resp):
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _errors(body) -> str:
    errs = body.get('erros') or []
    if errs and isinstance(errs, list):
        return '; '.join(str(e.get('mensagem') or e) for e in errs if e)[:500]
    return str(body.get('mensagem') or body.get('mensagem_sefaz') or '')[:500]


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None
