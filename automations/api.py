"""API das regras de automação (CAD-172). Prefixo: /api/v1/automations/

Ler: qualquer pessoa do escritório. Criar/editar/simular/ligar: dono ou administrador. Aprovar/recusar envio: dono, administrador
ou advogado (MEMBER) — perfil leitura não aprova. Tirar a aprovação humana de uma regra: só dono/administrador."""
from __future__ import annotations

from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import access
from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from automations import catalog, engine
from automations.models import Rule, RuleRun
from automations.templates import TEMPLATES, listing

APPROVER_ROLES = MANAGE_TEAM_ROLES | {'MEMBER'}


def rule_json(rule: Rule) -> dict:
    return {'id': rule.pk, 'nome': rule.name, 'descricao': rule.description, 'ativa': rule.enabled, 'gatilho': rule.trigger,
            'gatilho_label': rule.get_trigger_display(), 'gatilho_config': rule.trigger_config, 'condicoes': rule.conditions,
            'acoes': rule.actions, 'exige_aprovacao': rule.require_approval, 'modelo': rule.template_key,
            'simulada': rule.simulated, 'execucoes': rule.run_count, 'ultima_execucao': rule.last_run_at,
            'criada_em': rule.created_at, 'atualizada_em': rule.updated_at,
            'pendentes': rule.runs.filter(status=RuleRun.Status.PENDING).count()}


def run_json(run: RuleRun) -> dict:
    return {'id': run.pk, 'regra': {'id': run.rule_id, 'nome': run.rule.name}, 'gatilho': run.trigger, 'status': run.status,
            'status_label': run.get_status_display(), 'titulo': run.title, 'passos': run.steps, 'criada_em': run.created_at,
            'decidido_por': (run.decided_by.get_full_name() or run.decided_by.email) if run.decided_by else None,
            'decidido_em': run.decided_at, 'observacao': run.decision_note}


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def membership(self, request, roles=None):
        m = get_active_membership(request.user)
        if m is None:
            return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        perm = 'automacoes.gerir' if roles == MANAGE_TEAM_ROLES else 'automacoes.editar'      # grupo de acesso (CAD-223)
        if roles is not None and not access.allowed(m, perm, roles):
            return None, Response({'detail': 'Seu perfil não permite esta ação.'}, status=status.HTTP_403_FORBIDDEN)
        return m, None

    def rule(self, m, pk):
        return Rule.objects.filter(organization=m.organization, pk=pk).first()


class CatalogView(_Base):
    def get(self, request):
        _, err = self.membership(request)
        return err or Response(catalog.catalog())


class TemplateListView(_Base):
    def get(self, request):
        _, err = self.membership(request)
        return err or Response(listing())


class RuleListView(_Base):
    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        return Response([rule_json(r) for r in Rule.objects.filter(organization=m.organization)])

    def post(self, request):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        data = dict(request.data)
        key = data.pop('modelo', None) or data.pop('template', None)
        if key:
            if key not in TEMPLATES:
                return Response({'detail': 'Modelo desconhecido.'}, status=status.HTTP_400_BAD_REQUEST)
            data = {**TEMPLATES[key], **{k: v for k, v in data.items() if k == 'name' and v}}
        try:
            clean = catalog.clean_rule(data)
        except catalog.RuleError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        rule = Rule.objects.create(organization=m.organization, created_by=request.user, template_key=key or '', enabled=False, **clean)
        audit.log('automation.rule_created', actor=request.user, organization=m.organization, target=rule,
                  changes={'trigger': rule.trigger, 'actions': [a['type'] for a in rule.actions], 'modelo': key or ''})
        return Response(rule_json(rule), status=status.HTTP_201_CREATED)


class RuleDetailView(_Base):
    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        rule = self.rule(m, pk)
        return Response(rule_json(rule)) if rule else Response(status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        rule = self.rule(m, pk)
        if rule is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            clean = catalog.clean_rule(request.data, partial_of=rule)
        except catalog.RuleError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        for k, v in clean.items():
            setattr(rule, k, v)
        turned_off = rule.enabled and not rule.simulated              # mudou a lógica: desliga até simular de novo
        if turned_off:
            rule.enabled = False
        rule.save()
        audit.log('automation.rule_updated', actor=request.user, organization=m.organization, target=rule,
                  changes={'campos': sorted(clean), 'desligada': turned_off})
        return Response({**rule_json(rule), 'desligada_para_simular': turned_off})

    def delete(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        rule = self.rule(m, pk)
        if rule is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('automation.rule_deleted', actor=request.user, organization=m.organization, target=rule, changes={'nome': rule.name})
        rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RuleSimulateView(_Base):
    def post(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        rule = self.rule(m, pk)
        if rule is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({**engine.simulate(rule), 'regra': rule_json(rule)})


class RuleEnableView(_Base):
    """POST {ativa: true|false}. Ligar exige simulação da configuração atual."""

    def post(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        rule = self.rule(m, pk)
        if rule is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        on = request.data.get('ativa', True) is not False
        if on and not rule.simulated:
            return Response({'detail': 'Simule a regra antes de ligar (a configuração mudou ou ainda não foi simulada).',
                             'code': 'needs_simulation'}, status=status.HTTP_409_CONFLICT)
        rule.enabled = on
        rule.save(update_fields=['enabled', 'updated_at'])
        audit.log('automation.rule_enabled' if on else 'automation.rule_disabled', actor=request.user, organization=m.organization,
                  target=rule, changes={'exige_aprovacao': rule.require_approval})
        return Response(rule_json(rule))


class RunListView(_Base):
    """GET ?status=pending_approval&regra=ID — últimas 100 execuções."""

    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        qs = RuleRun.objects.filter(organization=m.organization).select_related('rule', 'decided_by')
        st = request.query_params.get('status')
        if st in RuleRun.Status.values:
            qs = qs.filter(status=st)
        if (rid := request.query_params.get('regra', '')).isdigit():
            qs = qs.filter(rule_id=int(rid))
        return Response([run_json(r) for r in qs[:100]])


class RunDecisionView(_Base):
    decision = 'approve'

    def post(self, request, pk):
        m, err = self.membership(request, APPROVER_ROLES)
        if err:
            return err
        run = RuleRun.objects.filter(organization=m.organization, pk=pk).select_related('rule').first()
        if run is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            with transaction.atomic():
                if self.decision == 'approve':
                    run = engine.approve(run, request.user)
                else:
                    run = engine.reject(run, request.user, str(request.data.get('motivo', '')))
        except engine.DecisionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(run_json(run))


class ComplianceView(_Base):
    """GET /api/v1/automations/conformidade/ — achados de conformidade das regras e dos acessos (CAD-223)."""

    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        from automations import governance
        return Response(governance.report(m.organization))
