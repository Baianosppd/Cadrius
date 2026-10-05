"""API do Motor Cadrius (CAD-165): Central de aprovações, regras do escritório, autonomia e memória. Prefixo: /api/v1/brain/"""
from __future__ import annotations

from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from brain import autonomy, feedback, memory
from brain.models import AutonomyProposal, MemoryItem, OfficeRule


def _ctx(request):
    membership = get_active_membership(request.user)
    if membership is None:
        return None, None
    return membership.organization, membership


def _no_org():
    return Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)


def _forbidden(msg='Apenas donos ou administradores.'):
    return Response({'detail': msg}, status=status.HTTP_403_FORBIDDEN)


def rule_payload(r: OfficeRule):
    return {'id': r.pk, 'kind': r.kind, 'field': r.field, 'from_value': r.from_value, 'to_value': r.to_value,
            'evidence': r.evidence, 'status': r.status, 'description': r.describe(), 'decided_at': r.decided_at}


def proposal_payload(p: AutonomyProposal):
    spec = autonomy.ACTION_KINDS[p.action_kind]
    return {'id': p.pk, 'action_kind': p.action_kind, 'label': spec['label'], 'risk': spec['risk'], 'from_mode': p.from_mode,
            'to_mode': p.to_mode, 'samples': p.samples, 'approval_rate': str(p.approval_rate), 'status': p.status, 'created_at': p.created_at}


class ApprovalsView(APIView):
    """GET — Central de aprovações: tudo o que a IA preparou e depende de uma decisão humana."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        from documents.models import DocumentExtraction
        reviews = (DocumentExtraction.objects.filter(document__organization=org, status=DocumentExtraction.Status.REVIEW)
                   .select_related('document').order_by('-updated_at')[:50])
        manager = membership.role in MANAGE_TEAM_ROLES
        pending_ai = 0
        try:
            from workflows.models import ExecutionLog
            pending_ai = ExecutionLog.objects.filter(workflow__organization=org, status='PENDING_REVIEW').count()
        except Exception:  # noqa: BLE001
            pending_ai = 0
        return Response({
            'document_reviews': [{'document_id': e.document_id, 'nome': e.document.nome, 'confidence': e.confidence, 'provider': e.provider,
                                  'message': e.message, 'updated_at': e.updated_at, 'prazos': len((e.fields or {}).get('prazos') or [])}
                                 for e in reviews],
            'automation_executions_pending': pending_ai,
            'rules_proposed': [rule_payload(r) for r in OfficeRule.objects.filter(organization=org, status='proposed')] if manager else [],
            'autonomy_proposals': [proposal_payload(p) for p in AutonomyProposal.objects.filter(organization=org, status='open')] if manager else [],
        })


class RulesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        return Response([rule_payload(r) for r in OfficeRule.objects.filter(organization=org).exclude(status='rejected')])


class RuleDecideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        if membership.role not in MANAGE_TEAM_ROLES:
            return _forbidden()
        rule = OfficeRule.objects.filter(pk=pk, organization=org).first()
        if rule is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            feedback.decide_rule(rule, request.user, request.data.get('decision'))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(rule_payload(rule))


class AutonomyView(APIView):
    """GET — matriz de autonomia com a taxa de acerto de cada ação (últimos 60 dias)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        rows = []
        for kind, spec in autonomy.ACTION_KINDS.items():
            s = autonomy.stats(org, kind)
            rows.append({'action_kind': kind, 'label': spec['label'], 'risk': spec['risk'], 'mode': autonomy.resolve(org, kind),
                         'allowed_modes': list(spec['allowed']), 'locked': spec['risk'] == 'R4',
                         'samples': s['samples'], 'approved': s['approved'], 'edited': s['edited'], 'rejected': s['rejected'],
                         'undone': s['undone'], 'approval_rate': str(s['approval_rate'])})
        return Response({'levels': rows, 'criteria': {'min_samples': autonomy.PROMO_MIN_SAMPLES, 'min_approval_rate': str(autonomy.PROMO_MIN_RATE),
                                                       'window_days': autonomy.PROMO_WINDOW_DAYS},
                         'proposals': [proposal_payload(p) for p in AutonomyProposal.objects.filter(organization=org, status='open')]})


class AutonomySetView(APIView):
    """PUT /autonomy/<action_kind>/ {mode} — só o DONO muda a autonomia."""
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, kind):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        if membership.role != 'OWNER':
            return _forbidden('Apenas o dono do escritório altera a autonomia da IA.')
        try:
            mode = autonomy.set_level(org, kind, request.data.get('mode'), request.user)
        except autonomy.AutonomyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'action_kind': kind, 'mode': mode})


class ProposalDecideView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        if membership.role != 'OWNER':
            return _forbidden('Apenas o dono do escritório decide a promoção de autonomia.')
        proposal = AutonomyProposal.objects.filter(pk=pk, organization=org).first()
        if proposal is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            autonomy.decide_proposal(proposal, request.user, request.data.get('decision') == 'approve')
        except autonomy.AutonomyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(proposal_payload(proposal))


class MemorySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[MemoryItem.Kind.TEMPLATE, MemoryItem.Kind.NOTE, MemoryItem.Kind.DECISION])
    title = serializers.CharField(max_length=160)
    text = serializers.CharField(max_length=memory.MAX_TEXT)


class MemoryView(APIView):
    """GET lista (sem os vetores) · POST adiciona modelo/anotação/decisão do escritório (dono/administrador)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        items = MemoryItem.objects.filter(organization=org).order_by('-created_at')[:200]
        return Response([{'id': i.pk, 'kind': i.kind, 'title': i.title, 'preview': i.text[:160], 'source': i.source,
                          'created_at': i.created_at} for i in items])

    def post(self, request):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        if membership.role not in MANAGE_TEAM_ROLES:
            return _forbidden()
        ser = MemorySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        item = memory.remember(org, d['kind'], d['text'], title=d['title'], user=request.user, source='manual')
        audit.log('memory.added', actor=request.user, organization=org, target=item, changes={'kind': d['kind']})
        return Response({'id': item.pk}, status=status.HTTP_201_CREATED)


class MemoryItemView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        if membership.role not in MANAGE_TEAM_ROLES:
            return _forbidden()
        item = MemoryItem.objects.filter(pk=pk, organization=org).first()
        if item is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('memory.deleted', actor=request.user, organization=org, changes={'kind': item.kind})
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemorySearchView(APIView):
    """GET ?q=...&kind=template — itens parecidos do PRÓPRIO escritório (ex.: modelos de peça relacionados)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org, membership = _ctx(request)
        if org is None:
            return _no_org()
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 3:
            return Response([])
        found = memory.similar(org, q, kind=request.query_params.get('kind') or None, k=5)
        return Response([{'id': i.pk, 'kind': i.kind, 'title': i.title, 'preview': i.text[:240], 'score': score} for score, i in found])


# ----------------------------------------------------------------------------- CAD-174: sugestões, perfil e aprendizado
def suggestion_payload(s):
    return {'id': s.pk, 'chave': s.key, 'titulo': s.title, 'motivo': s.reason, 'evidencia': s.evidence, 'status': s.status,
            'tipo': 'modelo' if (s.payload or {}).get('template') else 'regra', 'modelo': (s.payload or {}).get('template', ''),
            'regra_id': s.rule_id, 'criada_em': s.created_at, 'decidida_em': s.decided_at}


class SuggestionsView(APIView):
    """GET → abertas + últimas decididas. POST (dono/admin) → analisar agora."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from brain.models import AutomationSuggestion
        org, _ = _ctx(request)
        if org is None:
            return _no_org()
        qs = AutomationSuggestion.objects.filter(organization=org)
        return Response({'abertas': [suggestion_payload(s) for s in qs.filter(status='open')],
                         'recentes': [suggestion_payload(s) for s in qs.exclude(status='open')[:10]]})

    def post(self, request):
        from brain import suggestions
        org, m = _ctx(request)
        if org is None:
            return _no_org()
        if m.role not in MANAGE_TEAM_ROLES:
            return _forbidden()
        created = suggestions.refresh(org, notify=False)
        return Response({'novas': len(created), **self.get(request).data})


class SuggestionDecideView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    decision = 'accept'

    def post(self, request, pk):
        from brain import suggestions
        from brain.models import AutomationSuggestion
        org, m = _ctx(request)
        if org is None:
            return _no_org()
        if m.role not in MANAGE_TEAM_ROLES:
            return _forbidden()
        s = AutomationSuggestion.objects.filter(organization=org, pk=pk).first()
        if s is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            if self.decision == 'accept':
                rule = suggestions.accept(s, request.user)
                return Response({**suggestion_payload(s), 'regra_id': rule.pk})
            suggestions.dismiss(s, request.user)
        except suggestions.SuggestionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(suggestion_payload(s))


def profile_payload(p):
    from brain.profile import AREAS
    return {'areas': p.areas, 'publico': p.audience, 'cidade': p.city, 'tom': p.tone, 'assinatura': p.signature, 'redes': p.social,
            'calculado': p.auto_stats, 'opcoes_areas': [{'id': k, 'label': v} for k, v in AREAS.items()],
            'opcoes_tom': [{'id': k, 'label': v} for k, v in p.Tone.choices], 'atualizado_em': p.updated_at}


class ProfileView(APIView):
    """GET → perfil (recalcula a parte automática se tiver mais de 1 dia). PUT (dono/admin) → edita."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from brain import profile
        org, _ = _ctx(request)
        if org is None:
            return _no_org()
        p = profile.get(org)
        stamp = (p.auto_stats or {}).get('calculado_em', '')
        from datetime import timedelta

        from django.utils import timezone
        from django.utils.dateparse import parse_datetime
        when = parse_datetime(stamp) if stamp else None
        if when is None or timezone.now() - when > timedelta(days=1) or request.query_params.get('recalcular') == '1':
            p = profile.refresh_stats(org)
        return Response(profile_payload(p))

    def put(self, request):
        from brain import profile
        from brain.models import OfficeProfile
        org, m = _ctx(request)
        if org is None:
            return _no_org()
        if m.role not in MANAGE_TEAM_ROLES:
            return _forbidden()
        p = profile.get(org)
        d = request.data
        if 'areas' in d:
            areas = d.get('areas') if isinstance(d.get('areas'), list) else []
            unknown = [a for a in areas if a not in profile.AREAS]
            if unknown:
                return Response({'detail': f'Área desconhecida: {", ".join(map(str, unknown))}.'}, status=status.HTTP_400_BAD_REQUEST)
            p.areas = list(dict.fromkeys(areas))[:8]
        if 'tom' in d:
            if d['tom'] not in OfficeProfile.Tone.values:
                return Response({'detail': 'Tom inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            p.tone = d['tom']
        for key, field, limit in (('publico', 'audience', 200), ('cidade', 'city', 80), ('assinatura', 'signature', 1000)):
            if key in d:
                setattr(p, field, str(d.get(key) or '').strip()[:limit])
        if 'redes' in d and isinstance(d['redes'], dict):
            p.social = {k: str(v).strip()[:200] for k, v in d['redes'].items() if k in ('instagram', 'linkedin', 'site', 'facebook', 'youtube')}
        p.save()
        audit.log('brain.profile_updated', actor=request.user, organization=org, target=p, changes={'campos': sorted(d.keys())})
        return Response(profile_payload(p))


class InsightsView(APIView):
    """Quanto a IA está acertando e aprendendo neste escritório."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from brain import profile
        org, _ = _ctx(request)
        if org is None:
            return _no_org()
        try:
            days = max(7, min(365, int(request.query_params.get('dias', 90))))
        except ValueError:
            days = 90
        return Response(profile.insights(org, days))
