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
            'pendentes': rule.runs.filter(status=RuleRun.Status.PENDING).count(),
            'atalho_configurado': bool(rule.shortcut_key_hash)}


def run_json(run: RuleRun) -> dict:
    from automations.voice import code_for
    return {'codigo_relogio': code_for(run) if run.status == RuleRun.Status.PENDING else '', 'id': run.pk, 'regra': {'id': run.rule_id, 'nome': run.rule.name}, 'gatilho': run.trigger, 'status': run.status,
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


class RuleShortcutView(_Base):
    """CAD-226: POST gera (ou troca) o link secreto do atalho. A URL completa aparece só nesta resposta."""

    def post(self, request, pk):
        from automations import shortcuts
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        rule = self.rule(m, pk)
        if rule is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if rule.trigger != Rule.Trigger.SHORTCUT:
            return Response({'detail': 'Só regras com o gatilho "Atalho" têm link.'}, status=status.HTTP_400_BAD_REQUEST)
        url = shortcuts.rotate(rule, request)
        audit.log('automation.shortcut_rotated', actor=request.user, organization=m.organization, target=rule)
        return Response({'url': url, 'aviso': 'Guarde este link: ele não aparece de novo. Gerar outro invalida este.'})


class PublicShortcutView(APIView):
    """POST /api/v1/publico/atalho/<regra>/<chave>/ {texto?, origem?} — chamado pelo relógio, celular ou assistente de voz."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request, rule_id, key):
        from automations import shortcuts
        from core.queue import QueueUnavailable
        rule = Rule.objects.filter(pk=rule_id, trigger=Rule.Trigger.SHORTCUT).select_related('organization').first()
        if rule is None or not shortcuts.check(rule, key):
            return Response({'ok': False, 'mensagem': 'Atalho inválido.'}, status=status.HTTP_404_NOT_FOUND)
        if not rule.enabled or not rule.organization.is_active:
            return Response({'ok': False, 'mensagem': f'A regra "{rule.name}" está desligada no Cadrius.'}, status=status.HTTP_409_CONFLICT)
        if shortcuts.throttled(rule):
            return Response({'ok': False, 'mensagem': 'Muitos acionamentos em sequência. Espere um minuto.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        data = request.data if isinstance(request.data, dict) else {}
        texto = str(data.get('texto') or data.get('text') or '')
        try:
            shortcuts.fire(rule, texto, str(data.get('origem') or data.get('source') or ''))
        except QueueUnavailable:
            return Response({'ok': False, 'mensagem': 'O Cadrius não conseguiu receber agora. Tente de novo.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        audit.log('automation.shortcut_fired', actor_type='system', organization=rule.organization, target=rule,
                  changes={'texto_chars': len(texto)})
        return Response({'ok': True, 'mensagem': f'Feito: {rule.name}.'})


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


# ----------------------------------------------------------------------------- CAD-227: relógio e voz
def device_json(d) -> dict:
    return {'id': d.pk, 'nome': d.name, 'tipo': d.kind, 'tipo_label': d.get_kind_display(), 'aprova': d.can_approve,
            'avisos': d.notify, 'ntfy_topico': d.ntfy_topic, 'criado_em': d.created_at, 'ultimo_uso': d.last_used_at}


def _voice_urls(request, key: str, device) -> dict:
    from django.conf import settings
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/') or request.build_absolute_uri('/').rstrip('/')
    ntfy = (getattr(settings, 'NTFY_BASE_URL', '') or 'https://ntfy.sh').rstrip('/')
    return {'url_voz': f'{base}/api/v1/publico/voz/{key}/', 'chave': key,
            'url_avisos': f'{ntfy}/{device.ntfy_topic}' if device.ntfy_topic else ''}


class DeviceListView(_Base):
    """GET → meus aparelhos. POST {nome, tipo, aprova, avisos} → cria e devolve a chave UMA vez."""

    def get(self, request):
        from automations.models import PersonalDevice
        m, err = self.membership(request)
        if err:
            return err
        rows = PersonalDevice.objects.filter(organization=m.organization, user=request.user, revoked_at__isnull=True)
        return Response({'aparelhos': [device_json(d) for d in rows], 'pode_aprovar': m.role in engine_approver_roles(),
                         'pendentes': RuleRun.objects.filter(organization=m.organization, status=RuleRun.Status.PENDING).count(),
                         'tipos': [{'id': k, 'label': v} for k, v in PersonalDevice.Kind.choices]})

    def post(self, request):
        from automations import voice
        m, err = self.membership(request)
        if err:
            return err
        d = request.data
        from automations.models import PersonalDevice
        if PersonalDevice.objects.filter(user=request.user, organization=m.organization, revoked_at__isnull=True).count() >= 10:
            return Response({'detail': 'Limite de 10 aparelhos. Remova um que não usa mais.'}, status=status.HTTP_400_BAD_REQUEST)
        wants_approve = bool(d.get('aprova'))
        if wants_approve and m.role not in engine_approver_roles():
            return Response({'detail': 'O seu cargo não aprova envios.'}, status=status.HTTP_403_FORBIDDEN)
        device, key = voice.create_device(m.organization, request.user, name=str(d.get('nome') or ''), kind=str(d.get('tipo') or ''),
                                          can_approve=wants_approve, notify=bool(d.get('avisos')))
        return Response({**device_json(device), **_voice_urls(request, key, device),
                         'aviso': 'Guarde a chave agora: ela não aparece de novo.'}, status=status.HTTP_201_CREATED)


class DeviceDetailView(_Base):
    def delete(self, request, pk):
        from automations.models import PersonalDevice
        from django.utils import timezone
        m, err = self.membership(request)
        if err:
            return err
        d = PersonalDevice.objects.filter(pk=pk, user=request.user, organization=m.organization, revoked_at__isnull=True).first()
        if d is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        d.revoked_at = timezone.now()
        d.save(update_fields=['revoked_at'])
        audit.log('device.revoked', actor=request.user, organization=m.organization, target=d)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceTestView(_Base):
    """POST {texto, aparelho_id?} — experimenta um comando na tela. Leitura roda de verdade; ações só dizem o que fariam."""

    def post(self, request):
        from automations import voice
        from automations.models import PersonalDevice
        m, err = self.membership(request)
        if err:
            return err
        d = PersonalDevice.objects.filter(pk=request.data.get('aparelho_id'), user=request.user, revoked_at__isnull=True).first()
        if d is None:   # sem aparelho: testa como se fosse um aparelho que aprova (se o cargo deixa)
            d = PersonalDevice(organization=m.organization, user=request.user, name='teste',
                               can_approve=m.role in engine_approver_roles())
        return Response(voice.handle(d, str(request.data.get('texto') or '')[:500], dry_run=True))


def engine_approver_roles():
    return APPROVER_ROLES


def _voice_text(request) -> str:
    data = request.data if isinstance(request.data, dict) else {}
    text = data.get('texto') or data.get('text') or data.get('comando') or request.query_params.get('texto') or ''
    if not text and isinstance(request.data, str):
        text = request.data
    return str(text)[:500]


class PublicVoiceView(APIView):
    """POST /api/v1/publico/voz/<chave>/ {texto} → {ok, fala}. Chamado pelo relógio, Siri, Alexa, Google ou botão."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request, key):
        from django.utils import timezone
        from automations import voice
        device = voice.device_for(key)
        if device is None:
            return Response({'ok': False, 'fala': 'Aparelho não reconhecido. Cadastre de novo em Cadrius → Relógio e voz.'},
                            status=status.HTTP_404_NOT_FOUND)
        if voice.throttled(device):
            return Response({'ok': False, 'fala': 'Muitos comandos seguidos. Espere um minuto.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        type(device).objects.filter(pk=device.pk).update(last_used_at=timezone.now())
        out = voice.handle(device, _voice_text(request))
        audit.log('device.command', actor=device.user, organization=device.organization,
                  changes={'acao': out.get('acao'), 'ok': out.get('ok'), 'aparelho': device.pk})
        return Response(out)


class PublicWatchDecisionView(APIView):
    """POST /api/v1/publico/relogio/decidir/<token>/ — botões "Aprovar"/"Recusar" do aviso no relógio (vale 24 h)."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def post(self, request, token):
        from automations import voice
        out = voice.decide_by_token(token)
        return Response(out, status=status.HTTP_200_OK if out.get('ok') else status.HTTP_400_BAD_REQUEST)
