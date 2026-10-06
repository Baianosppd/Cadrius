"""Setor Fiscal da Cadrius — fase 1 (CAD-170): livro de recebimentos, registro manual da NF emitida e exportação para o contador.
Fase 2 (emissão de NFS-e por emissor) e fase 3 (obrigações/reforma tributária): docs/PLANO_PROXIMA_FASE.md §10."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from audit import service as audit
from backoffice.services import ActionError
from billing.models import Payment


def parse_period(start: str | None, end: str | None):
    """Período em datas locais [start, end]. Padrão: mês corrente."""
    today = timezone.localdate()
    try:
        d0 = date.fromisoformat(start) if start else today.replace(day=1)
        d1 = date.fromisoformat(end) if end else today
    except ValueError as exc:
        raise ActionError('Datas no formato AAAA-MM-DD.') from exc
    if d1 < d0:
        raise ActionError('A data final é anterior à inicial.')
    if (d1 - d0).days > 400:
        raise ActionError('Período máximo: 400 dias.')
    tz = timezone.get_current_timezone()
    return d0, d1, timezone.make_aware(datetime.combine(d0, time.min), tz), timezone.make_aware(datetime.combine(d1 + timedelta(days=1), time.min), tz)


def payments_qs(start, end, status=None):
    d0, d1, t0, t1 = parse_period(start, end)
    qs = Payment.objects.filter(paid_at__gte=t0, paid_at__lt=t1).select_related('organization', 'organization__plan')
    if status in Payment.InvoiceStatus.values:
        qs = qs.filter(invoice_status=status)
    return d0, d1, qs


def _tomador(org) -> dict:
    """Quem recebe a nota: razão social + CNPJ do escritório; para conta individual, o CPF do dono."""
    doc = org.cnpj or ''
    if not doc:
        owner = org.members.filter(role='OWNER', is_active=True).select_related('user').first()
        doc = (owner.user.cpf or '') if owner else ''
    return {'nome': org.razao_social or str(org), 'documento': doc}


def payment_row(p) -> dict:
    return {'id': p.pk, 'pago_em': p.paid_at, 'escritorio': str(p.organization), 'tomador': _tomador(p.organization),
            'tipo': p.kind, 'tipo_label': p.get_kind_display(), 'descricao': p.description, 'valor_brl': f'{p.amount_cents / 100:.2f}',
            'nf_status': p.invoice_status, 'nf_numero': p.invoice_number, 'nf_emitida_em': p.invoice_issued_at, 'nf_obs': p.invoice_note}


def summary(qs) -> dict:
    by_kind = {row['kind']: {'quantidade': row['n'], 'total_brl': f'{(row["t"] or 0) / 100:.2f}'}
               for row in qs.values('kind').annotate(n=Count('id'), t=Sum('amount_cents'))}
    total = qs.aggregate(t=Sum('amount_cents'))['t'] or 0
    return {'total_brl': f'{total / 100:.2f}', 'quantidade': qs.count(), 'por_tipo': by_kind,
            'nf_pendentes': qs.filter(invoice_status=Payment.InvoiceStatus.PENDING).count(), 'faturamento_12m': revenue_12m()}


# Limites de faturamento anual (LC 123/2006): Simples Nacional R$ 4,8 mi; sublimite estadual/municipal (ISS e ICMS no DAS) R$ 3,6 mi.
SIMPLES_LIMIT, SUBLIMIT = 4_800_000_00, 3_600_000_00


def revenue_12m(today=None) -> dict:
    """CAD-223: receita bruta dos últimos 12 meses (RBT12) e alerta de proximidade dos limites do Simples."""
    from datetime import timedelta
    today = today or timezone.localdate()
    start = today.replace(day=1) - timedelta(days=365)
    total = Payment.objects.filter(paid_at__date__gte=start, paid_at__date__lt=today.replace(day=1)).aggregate(t=Sum('amount_cents'))['t'] or 0
    alert = ''
    if total >= SIMPLES_LIMIT * 0.8:
        alert = 'Faturamento acima de 80% do limite do Simples Nacional (R$ 4,8 mi): fale com o contador sobre o regime.'
    elif total >= SUBLIMIT * 0.8:
        alert = 'Faturamento perto do sublimite de R$ 3,6 mi (ISS passa a ser recolhido fora do DAS): avise o contador.'
    return {'rbt12_brl': f'{total / 100:.2f}', 'uso_do_limite_pct': round(100 * total / SIMPLES_LIMIT, 1), 'alerta': alert}


def register_invoice(actor, payment, *, status, number, issued_at, note, reason):
    if status not in (Payment.InvoiceStatus.ISSUED, Payment.InvoiceStatus.NOT_REQUIRED, Payment.InvoiceStatus.PENDING):
        raise ActionError('Situação da NF inválida.')
    number = (number or '').strip()[:60]
    if status == Payment.InvoiceStatus.ISSUED:
        if not number:
            raise ActionError('Informe o número da NF emitida.')
        try:
            issued = date.fromisoformat(issued_at) if issued_at else timezone.localdate()
        except ValueError as exc:
            raise ActionError('Data de emissão no formato AAAA-MM-DD.') from exc
    else:
        issued, number = None, ''
    payment.invoice_status, payment.invoice_number, payment.invoice_issued_at = status, number, issued
    payment.invoice_note = (note or '').strip()[:255]
    payment.save(update_fields=['invoice_status', 'invoice_number', 'invoice_issued_at', 'invoice_note'])
    audit.log('backoffice.action', actor=actor, organization=payment.organization, target=payment, reason=reason[:255],
              changes={'action': 'fiscal_invoice', 'status': status, 'number': number})
    return payment_row(payment)


def export_csv(qs) -> str:
    """CSV para o contador (separador ';' e vírgula decimal, como o Excel em português abre)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    w.writerow(['Pago em', 'Tomador', 'CPF/CNPJ', 'Escritório', 'Tipo', 'Descrição', 'Valor (R$)', 'Situação NF', 'Nº NF',
                'Emitida em', 'ID Stripe'])
    for p in qs.order_by('paid_at'):
        t = _tomador(p.organization)
        w.writerow([timezone.localtime(p.paid_at).strftime('%d/%m/%Y %H:%M'), t['nome'], t['documento'], str(p.organization),
                    p.get_kind_display(), p.description, f'{p.amount_cents / 100:.2f}'.replace('.', ','), p.get_invoice_status_display(),
                    p.invoice_number, p.invoice_issued_at.strftime('%d/%m/%Y') if p.invoice_issued_at else '', p.stripe_id])
    return buf.getvalue()
