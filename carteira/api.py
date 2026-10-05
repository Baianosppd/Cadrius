"""API da carteira (funil + contratos) e do financeiro do escritório (CAD-175). Prefixo: /api/v1/carteira/

Permissões: funil e contratos — leitura de todos, escrita de dono/admin/membro; financeiro (lançamentos, baixa, painel) — dono/admin;
despesas — dono/admin/membro podem lançar (custas do dia a dia), só dono/admin apagam. Webhook do Asaas: público, autenticado pelo
token do cabeçalho ``asaas-access-token`` (comparação em tempo constante) e idempotente.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from carteira import services as svc
from carteira.models import Expense, FeeAgreement, Opportunity, Receivable
from contacts.models import Contact

WRITE_ROLES = {'OWNER', 'ADMIN', 'MEMBER'}
PAGE = 100


def _bad(msg, code=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({'detail': msg, **extra}, status=code)


def _person(c):
    return {'id': c.pk, 'nome': c.name} if c else None


def _case(c):
    return {'id': c.pk, 'cnj': c.cnj, 'apelido': c.label} if c else None


def opp_json(o: Opportunity) -> dict:
    return {'id': o.pk, 'titulo': o.title, 'contato': _person(o.contact), 'area': o.area, 'etapa': o.stage,
            'etapa_label': o.get_stage_display(), 'origem': o.source, 'origem_label': o.get_source_display(),
            'valor_centavos': o.value_cents, 'responsavel': {'id': o.owner_id, 'nome': o.owner.get_full_name() or o.owner.email} if o.owner_id else None,
            'proxima_acao': o.next_action, 'proxima_acao_em': o.next_action_at, 'motivo_perda': o.lost_reason, 'observacoes': o.notes,
            'atrasada': bool(o.next_action_at and o.stage in Opportunity.OPEN_STAGES and o.next_action_at < timezone.localdate()),
            'etapa_desde': o.stage_changed_at, 'criada_em': o.created_at}


def rec_json(r: Receivable, today=None) -> dict:
    today = today or timezone.localdate()
    return {'id': r.pk, 'descricao': r.description, 'contato': _person(r.contact), 'processo': _case(r.case),
            'contrato_id': r.agreement_id, 'valor_centavos': r.amount_cents, 'vencimento': r.due_date, 'status': r.status,
            'vencido': r.status == Receivable.Status.OPEN and r.due_date < today, 'dias_atraso': svc.overdue_days(r, today) if r.status == 'aberto' else 0,
            'pago_em': r.paid_at, 'pago_centavos': r.paid_cents, 'forma': r.method, 'link_pagamento': r.payment_url,
            'no_asaas': bool(r.asaas_id), 'obs': r.notes}


def ag_json(a: FeeAgreement, with_items=False) -> dict:
    data = {'id': a.pk, 'titulo': a.title, 'contato': _person(a.contact), 'processo': _case(a.case), 'tipo': a.kind,
            'tipo_label': a.get_kind_display(), 'valor_centavos': a.total_cents, 'parcelas': a.installments, 'primeiro_vencimento': a.first_due,
            'exito_pct': str(a.success_pct), 'status': a.status, 'oportunidade_id': a.opportunity_id, 'observacoes': a.notes,
            'criado_em': a.created_at}
    recs = list(a.receivables.all())
    data['recebido_centavos'] = sum(r.paid_cents for r in recs if r.status == 'pago')
    data['em_aberto_centavos'] = sum(r.amount_cents for r in recs if r.status == 'aberto')
    if with_items:
        data['lancamentos'] = [rec_json(r) for r in recs]
    return data


def exp_json(e: Expense) -> dict:
    return {'id': e.pk, 'descricao': e.description, 'categoria': e.category, 'categoria_label': e.get_category_display(),
            'valor_centavos': e.amount_cents, 'data': e.date, 'contato': _person(e.contact), 'processo': _case(e.case),
            'reembolsavel': e.reimbursable, 'reembolso': rec_json(e.reimbursement) if e.reimbursement_id else None}


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def membership(self, request, roles=None):
        m = get_active_membership(request.user)
        if m is None:
            return None, _bad('Usuário sem escritório.', status.HTTP_403_FORBIDDEN)
        if roles and m.role not in roles:
            return None, _bad('Seu perfil não permite esta ação.', status.HTTP_403_FORBIDDEN)
        return m, None

    def contact(self, org, pk, required=True):
        c = Contact.objects.filter(organization=org, pk=pk).first() if pk else None
        if c is None and required:
            raise svc.FinanceError('Escolha um contato do quadro.')
        return c

    def case(self, org, pk):
        if not pk:
            return None
        from research.models import MonitoredCase
        c = MonitoredCase.objects.filter(organization=org, pk=pk).first()
        if c is None:
            raise svc.FinanceError('Processo não encontrado.')
        return c

    def user_in_org(self, org, pk):
        if not pk:
            return None
        from accounts.models import OrganizationMembership as Membership
        m = Membership.objects.filter(organization=org, user_id=pk, is_active=True).select_related('user').first()
        if m is None:
            raise svc.FinanceError('Responsável precisa ser da equipe.')
        return m.user


def _period(request):
    today = timezone.localdate()
    start = request.query_params.get('inicio') or today.replace(day=1).isoformat()
    end = request.query_params.get('fim') or today.isoformat()
    d0, d1 = svc.to_date(start, 'data inicial'), svc.to_date(end, 'data final')
    if d1 < d0 or (d1 - d0).days > 400:
        raise svc.FinanceError('Período inválido (máximo de 400 dias).')
    return d0, d1


# ----------------------------------------------------------------------------- funil
OPP_FIELDS = {'titulo': 'title', 'area': 'area', 'origem': 'source', 'proxima_acao': 'next_action', 'observacoes': 'notes'}


class OpportunitiesView(_Base):
    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        qs = Opportunity.objects.filter(organization=m.organization).select_related('contact', 'owner')
        if request.query_params.get('abertas') == '1':
            qs = qs.filter(stage__in=Opportunity.OPEN_STAGES)
        if request.query_params.get('contato'):
            qs = qs.filter(contact_id=request.query_params['contato'])
        return Response({'resultados': [opp_json(o) for o in qs[:300]], 'etapas': Opportunity.Stage.choices,
                         'origens': Opportunity.Source.choices, 'resumo': svc.funnel(m.organization)})

    def post(self, request):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        return self._save(request, m, Opportunity(organization=m.organization, created_by=request.user, owner=request.user),
                          status.HTTP_201_CREATED)

    def _save(self, request, m, opp, code):
        d = request.data
        try:
            if opp.pk is None or 'contato_id' in d:
                opp.contact = self.contact(m.organization, d.get('contato_id'))
            for key, attr in OPP_FIELDS.items():
                if key in d:
                    setattr(opp, attr, str(d.get(key) or '').strip()[:2000 if key == 'observacoes' else 160])
            if not (opp.title or '').strip():
                raise svc.FinanceError('Dê um título (ex.: "Revisional de aposentadoria").')
            if opp.source not in Opportunity.Source.values:
                raise svc.FinanceError('Origem inválida.')
            if 'valor' in d:
                opp.value_cents = svc.to_cents(d.get('valor'), allow_zero=True)
            if 'proxima_acao_em' in d:
                opp.next_action_at = svc.to_date(d['proxima_acao_em'], 'data da próxima ação') if d.get('proxima_acao_em') else None
            if 'responsavel_id' in d:
                opp.owner = self.user_in_org(m.organization, d.get('responsavel_id'))
            opp.save()
            if d.get('etapa') and d['etapa'] != opp.stage:
                svc.move_stage(opp, d['etapa'], request.user, d.get('motivo_perda', ''))
        except svc.FinanceError as exc:
            return _bad(str(exc))
        audit.log('crm.opportunity_saved', actor=request.user, organization=m.organization, target=opp, changes={'etapa': opp.stage})
        return Response(opp_json(opp), status=code)


class OpportunityDetailView(OpportunitiesView):
    def get_obj(self, m, pk):
        return Opportunity.objects.filter(organization=m.organization, pk=pk).select_related('contact', 'owner').first()

    def patch(self, request, pk):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        opp = self.get_obj(m, pk)
        if opp is None:
            return _bad('Oportunidade não encontrada.', status.HTTP_404_NOT_FOUND)
        return self._save(request, m, opp, status.HTTP_200_OK)

    def delete(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        opp = self.get_obj(m, pk)
        if opp is None:
            return _bad('Oportunidade não encontrada.', status.HTTP_404_NOT_FOUND)
        opp.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------------- contratos
class AgreementsView(_Base):
    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        qs = FeeAgreement.objects.filter(organization=m.organization).select_related('contact', 'case').prefetch_related('receivables')
        if request.query_params.get('contato'):
            qs = qs.filter(contact_id=request.query_params['contato'])
        if request.query_params.get('status') in FeeAgreement.Status.values:
            qs = qs.filter(status=request.query_params['status'])
        return Response({'resultados': [ag_json(a) for a in qs[:PAGE]], 'tipos': FeeAgreement.Kind.choices})

    def post(self, request):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        d = request.data
        try:
            contact = self.contact(m.organization, d.get('contato_id'))
            kind = d.get('tipo')
            opp = Opportunity.objects.filter(organization=m.organization, pk=d.get('oportunidade_id')).first() if d.get('oportunidade_id') else None
            ag = svc.create_agreement(
                m.organization, request.user, contact=contact, title=str(d.get('titulo') or 'Honorários advocatícios').strip(), kind=kind,
                total_cents=svc.to_cents(d.get('valor'), allow_zero=kind == FeeAgreement.Kind.SUCCESS),
                installments=int(d.get('parcelas') or 1), success_pct=str(d.get('exito_pct') or '0').replace(',', '.'),
                first_due=svc.to_date(d['primeiro_vencimento'], '1º vencimento') if d.get('primeiro_vencimento') else None,
                case=self.case(m.organization, d.get('processo_id')), opportunity=opp, notes=str(d.get('observacoes') or '')[:2000])
        except (svc.FinanceError, ValueError) as exc:
            return _bad(str(exc) if isinstance(exc, svc.FinanceError) else 'Dados do contrato inválidos.')
        return Response(ag_json(ag, with_items=True), status=status.HTTP_201_CREATED)


class AgreementDetailView(_Base):
    def obj(self, m, pk):
        return FeeAgreement.objects.filter(organization=m.organization, pk=pk).select_related('contact', 'case').first()

    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        ag = self.obj(m, pk)
        return Response(ag_json(ag, with_items=True)) if ag else _bad('Contrato não encontrado.', status.HTTP_404_NOT_FOUND)

    def post(self, request, pk, action):
        m, err = self.membership(request, MANAGE_TEAM_ROLES if action == 'cancelar' else WRITE_ROLES)
        if err:
            return err
        ag = self.obj(m, pk)
        if ag is None:
            return _bad('Contrato não encontrado.', status.HTTP_404_NOT_FOUND)
        try:
            if action == 'cancelar':
                svc.cancel_agreement(ag, request.user)
            elif action == 'exito':
                svc.register_success(ag, request.user, benefit_cents=svc.to_cents(request.data.get('proveito')),
                                     due_date=svc.to_date(request.data.get('vencimento'), 'data de vencimento'))
            else:
                return _bad('Ação inválida.', status.HTTP_404_NOT_FOUND)
        except svc.FinanceError as exc:
            return _bad(str(exc))
        ag.refresh_from_db()
        return Response(ag_json(ag, with_items=True))


# ----------------------------------------------------------------------------- financeiro
class ReceivablesView(_Base):
    def get(self, request):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        today = timezone.localdate()
        qs = Receivable.objects.filter(organization=m.organization).select_related('contact', 'case')
        f = request.query_params.get('filtro', 'aberto')
        if f == 'aberto':
            qs = qs.filter(status=Receivable.Status.OPEN)
        elif f == 'vencido':
            qs = qs.filter(status=Receivable.Status.OPEN, due_date__lt=today)
        elif f == 'pago':
            qs = qs.filter(status=Receivable.Status.PAID).order_by('-paid_at', '-id')
        if request.query_params.get('contato'):
            qs = qs.filter(contact_id=request.query_params['contato'])
        return Response({'resultados': [rec_json(r, today) for r in qs[:300]], 'formas': Receivable.Method.choices})

    def post(self, request):
        """Lançamento avulso (consulta, parecer, reembolso…)."""
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        d = request.data
        try:
            rec = Receivable.objects.create(
                organization=m.organization, contact=self.contact(m.organization, d.get('contato_id')),
                case=self.case(m.organization, d.get('processo_id')), description=(str(d.get('descricao') or '').strip() or 'Honorários')[:200],
                amount_cents=svc.to_cents(d.get('valor')), due_date=svc.to_date(d.get('vencimento'), 'data de vencimento'),
                notes=str(d.get('obs') or '')[:255], created_by=request.user)
        except svc.FinanceError as exc:
            return _bad(str(exc))
        audit.log('finance.receivable_saved', actor=request.user, organization=m.organization, target=rec,
                  changes={'valor_centavos': rec.amount_cents}, data_categories=['financeiro'])
        return Response(rec_json(rec), status=status.HTTP_201_CREATED)


class ReceivableActionView(_Base):
    def post(self, request, pk, action):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        rec = Receivable.objects.filter(organization=m.organization, pk=pk).select_related('contact', 'agreement').first()
        if rec is None:
            return _bad('Lançamento não encontrado.', status.HTTP_404_NOT_FOUND)
        d = request.data
        try:
            if action == 'baixa':
                svc.mark_paid(rec, request.user, paid_at=svc.to_date(d['pago_em'], 'data do pagamento') if d.get('pago_em') else None,
                              paid_cents=svc.to_cents(d['valor']) if d.get('valor') else None, method=d.get('forma', ''))
            elif action == 'reabrir':
                svc.reopen(rec, request.user)
            elif action == 'cancelar':
                if rec.status != Receivable.Status.OPEN:
                    raise svc.FinanceError('Só lançamentos em aberto podem ser cancelados.')
                rec.status = Receivable.Status.CANCELED
                rec.save(update_fields=['status', 'updated_at'])
                audit.log('finance.receivable_saved', actor=request.user, organization=m.organization, target=rec, changes={'status': 'cancelado'})
            elif action == 'cobrar':
                svc.charge(rec, request.user, d.get('forma') if d.get('forma') in ('BOLETO', 'PIX', 'UNDEFINED') else 'UNDEFINED')
            else:
                return _bad('Ação inválida.', status.HTTP_404_NOT_FOUND)
        except svc.FinanceError as exc:
            return _bad(str(exc))
        except Exception as exc:  # noqa: BLE001 — erro do provedor vira mensagem
            from integrations.services import IntegrationError
            if isinstance(exc, IntegrationError):
                return _bad(str(exc), status.HTTP_502_BAD_GATEWAY)
            raise
        rec.refresh_from_db()
        return Response(rec_json(rec))


class ExpensesView(_Base):
    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        try:
            d0, d1 = _period(request)
        except svc.FinanceError as exc:
            return _bad(str(exc))
        qs = Expense.objects.filter(organization=m.organization, date__gte=d0, date__lte=d1).select_related('contact', 'case', 'reimbursement')
        if request.query_params.get('processo'):
            qs = qs.filter(case_id=request.query_params['processo'])
        return Response({'resultados': [exp_json(e) for e in qs[:300]], 'categorias': Expense.Category.choices})

    def post(self, request):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        d = request.data
        try:
            exp = svc.create_expense(
                m.organization, request.user, description=(str(d.get('descricao') or '').strip() or 'Despesa'),
                category=d.get('categoria') or 'custas', amount_cents=svc.to_cents(d.get('valor')),
                when=svc.to_date(d.get('data') or timezone.localdate().isoformat()), case=self.case(m.organization, d.get('processo_id')),
                contact=self.contact(m.organization, d.get('contato_id'), required=False), reimbursable=bool(d.get('reembolsavel')))
        except svc.FinanceError as exc:
            return _bad(str(exc))
        return Response(exp_json(exp), status=status.HTTP_201_CREATED)


class ExpenseDetailView(_Base):
    def delete(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        exp = Expense.objects.filter(organization=m.organization, pk=pk).select_related('reimbursement').first()
        if exp is None:
            return _bad('Despesa não encontrada.', status.HTTP_404_NOT_FOUND)
        if exp.reimbursement_id and exp.reimbursement.status == Receivable.Status.PAID:
            return _bad('O reembolso desta despesa já foi recebido: reabra o lançamento antes de apagar.')
        if exp.reimbursement_id:
            exp.reimbursement.delete()
        audit.log('finance.expense_deleted', actor=request.user, organization=m.organization, target=exp,
                  changes={'valor_centavos': exp.amount_cents})
        exp.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SummaryView(_Base):
    def get(self, request):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        try:
            d0, d1 = _period(request)
        except svc.FinanceError as exc:
            return _bad(str(exc))
        return Response({**svc.summary(m.organization, d0, d1), 'funil': svc.funnel(m.organization)})


class ClientView(_Base):
    """Ficha do cliente na carteira: oportunidades, contratos, financeiro e processos — tudo de um contato."""

    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        c = Contact.objects.filter(organization=m.organization, pk=pk).first()
        if c is None:
            return _bad('Contato não encontrado.', status.HTTP_404_NOT_FOUND)
        finance = m.role in MANAGE_TEAM_ROLES
        recs = Receivable.objects.filter(organization=m.organization, contact=c).select_related('case')
        today = timezone.localdate()
        data = {'contato': {'id': c.pk, 'nome': c.name, 'tipo': c.get_kind_display()},
                'oportunidades': [opp_json(o) for o in c.opportunities.select_related('owner')],
                'contratos': [ag_json(a) for a in c.fee_agreements.prefetch_related('receivables').select_related('case')],
                'processos': [_case(x) for x in c.cases.filter(is_active=True)]}
        if finance:
            data['financeiro'] = {
                'lancamentos': [rec_json(r, today) for r in recs.exclude(status=Receivable.Status.CANCELED)[:100]],
                'em_aberto_centavos': sum(r.amount_cents for r in recs if r.status == 'aberto'),
                'vencido_centavos': sum(r.amount_cents for r in recs if r.status == 'aberto' and r.due_date < today),
                'recebido_centavos': sum(r.paid_cents for r in recs if r.status == 'pago')}
        return Response(data)


# ----------------------------------------------------------------------------- Asaas: webhook
class AsaasWebhookConfigView(_Base):
    """POST — gera o token e devolve a URL + token para colar no painel do Asaas (Integrações → Webhooks)."""

    def post(self, request):
        from integrations.services import org_connection
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        conn = org_connection(m.organization, 'ASAAS')
        if conn is None:
            return _bad('Conecte o Asaas em Integrações primeiro.', status.HTTP_409_CONFLICT, code='not_connected')
        token = svc.webhook_config(conn)
        audit.log('finance.webhook_configured', actor=request.user, organization=m.organization, target=conn, changes={'provedor': 'asaas'})
        url = request.build_absolute_uri(f'/api/v1/carteira/asaas/webhook/{conn.pk}/')
        return Response({'url': url, 'token': token, 'eventos': sorted(svc.PAID_EVENTS | svc.REOPEN_EVENTS | svc.CANCEL_EVENTS)})


class WebhookThrottle(AnonRateThrottle):
    rate = '120/min'


class AsaasWebhookView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [WebhookThrottle]

    def post(self, request, conn_id):
        from accounts.team_roles import get_active_membership as _gm
        from integrations.models import AppConnection
        conn = AppConnection.objects.filter(pk=conn_id, app_name='ASAAS', is_active=True).select_related('user').first()
        if conn is None or not svc.token_ok(conn, request.headers.get('asaas-access-token', '')):
            return Response({'detail': 'não autorizado'}, status=status.HTTP_401_UNAUTHORIZED)
        m = _gm(conn.user)
        if m is None:
            return Response({'detail': 'conexão sem escritório'}, status=status.HTTP_409_CONFLICT)
        payload = request.data if isinstance(request.data, dict) else {}
        result = svc.handle_asaas_event(m.organization, payload)
        return Response({'ok': True, 'resultado': result})
