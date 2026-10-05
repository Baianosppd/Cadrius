"""API de marketing (CAD-174).

Escritório: /api/v1/marketing/… — ler: todos; criar/editar: dono, administrador e advogado; aprovar, agendar e publicar: dono e
administrador (é a voz pública do escritório).
Cadrius: /api/v1/backoffice/marketing/… — área Marketing da Gestão (com MFA), mesmo fluxo + indicadores de crescimento.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from backoffice.permissions import HasArea
from marketing import compliance, ideas, services
from marketing.models import Campaign, ContentPiece

WRITE_ROLES = MANAGE_TEAM_ROLES | {'MEMBER'}
PS = ContentPiece.Status


def piece_json(p, full=True):
    data = {'id': p.pk, 'canal': p.channel, 'canal_label': p.get_channel_display(), 'tema': p.theme, 'titulo': p.title,
            'status': p.status, 'status_label': p.get_status_display(), 'agendado_para': p.scheduled_at, 'publicado_em': p.published_at,
            'campanha_id': p.campaign_id, 'alertas': p.compliance, 'bloqueado': compliance.blocking(p.compliance),
            'automatico': p.channel in services.AUTO_CHANNELS, 'erro': p.publish_error, 'ia': p.ai_provider,
            'criado_em': p.created_at, 'atualizado_em': p.updated_at}
    if full:
        data.update(texto=p.body, hashtags=p.hashtags, sugestao_imagem=p.image_hint, imagem_url=p.image_url,
                    texto_final=services.full_text(p))
    return data


def campaign_json(c):
    return {'id': c.pk, 'nome': c.name, 'objetivo': c.goal, 'publico': c.audience, 'canais': c.channels, 'inicio': c.starts_on,
            'fim': c.ends_on, 'notas': c.notes, 'conteudos': c.pieces.count(), 'criada_em': c.created_at}


class _Scoped(APIView):
    """Resolve escopo, escritório e permissões. Subclasses de staff trocam ``scope``."""
    permission_classes = [permissions.IsAuthenticated]
    scope = 'escritorio'

    def ctx(self, request, need=None):
        """need: None (ler) | 'write' | 'approve'. Devolve (org, erro)."""
        if self.scope == 'cadrius':
            return None, None                          # a permissão de área (HasArea) já valeu
        m = get_active_membership(request.user)
        if m is None:
            return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        roles = {'write': WRITE_ROLES, 'approve': MANAGE_TEAM_ROLES}.get(need)
        if roles and m.role not in roles:
            msg = 'Só dono ou administrador aprova e publica conteúdo.' if need == 'approve' else 'Seu perfil não permite esta ação.'
            return None, Response({'detail': msg}, status=status.HTTP_403_FORBIDDEN)
        return m.organization, None

    def pieces(self, org):
        qs = ContentPiece.objects.filter(scope=self.scope)
        return qs.filter(organization=org) if self.scope == 'escritorio' else qs

    def campaigns(self, org):
        qs = Campaign.objects.filter(scope=self.scope)
        return qs.filter(organization=org) if self.scope == 'escritorio' else qs


class IdeasView(_Scoped):
    def get(self, request):
        org, err = self.ctx(request)
        if err:
            return err
        if self.scope == 'cadrius':
            return Response(ideas.cadrius_ideas())
        from brain.profile import get as get_profile
        return Response({**ideas.office_ideas(get_profile(org).areas), 'canais': ContentPiece.Channel.choices})


class CheckView(_Scoped):
    def post(self, request):
        org, err = self.ctx(request)
        if err:
            return err
        text = str(request.data.get('texto', ''))[:25000]
        alerts = compliance.check(text, self.scope, str(request.data.get('canal', '')))
        return Response({'alertas': alerts, 'bloqueado': compliance.blocking(alerts)})


class PieceListView(_Scoped):
    """GET ?status=&de=AAAA-MM-DD&ate=AAAA-MM-DD → lista; POST {canal, tema, orientacoes, usar_ia, campanha_id} → gera rascunho."""

    def get(self, request):
        org, err = self.ctx(request)
        if err:
            return err
        qs = self.pieces(org)
        st = request.query_params.get('status')
        if st in PS.values:
            qs = qs.filter(status=st)
        start, end = parse_date(request.query_params.get('de') or ''), parse_date(request.query_params.get('ate') or '')
        if start:
            qs = qs.filter(scheduled_at__date__gte=start)
        if end:
            qs = qs.filter(scheduled_at__date__lte=end)
        counts = {s: self.pieces(org).filter(status=s).count() for s in PS.values}
        return Response({'contagem': counts, 'resultados': [piece_json(p, full=False) for p in qs[:300]]})

    def post(self, request):
        org, err = self.ctx(request, 'write')
        if err:
            return err
        d = request.data
        channel, theme = d.get('canal'), str(d.get('tema') or '').strip()
        if channel not in ContentPiece.Channel.values:
            return Response({'detail': 'Escolha o canal.'}, status=status.HTTP_400_BAD_REQUEST)
        if not 5 <= len(theme) <= 200:
            return Response({'detail': 'Descreva o tema (5 a 200 caracteres).'}, status=status.HTTP_400_BAD_REQUEST)
        campaign = self.campaigns(org).filter(pk=d.get('campanha_id')).first() if d.get('campanha_id') else None
        piece, notice = services.generate(scope=self.scope, org=org, user=request.user, channel=channel, theme=theme,
                                          brief=str(d.get('orientacoes') or '')[:1000], use_ai=d.get('usar_ia') is not False,
                                          campaign=campaign)
        audit.log('marketing.content_created', actor=request.user, organization=org, target=piece,
                  changes={'canal': channel, 'escopo': self.scope, 'ia': piece.ai_provider or 'nao'})
        return Response({**piece_json(piece), 'aviso': notice}, status=status.HTTP_201_CREATED)


class PieceDetailView(_Scoped):
    def _get(self, org, pk):
        return self.pieces(org).filter(pk=pk).first()

    def get(self, request, pk):
        org, err = self.ctx(request)
        if err:
            return err
        p = self._get(org, pk)
        return Response(piece_json(p)) if p else Response(status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, pk):
        d = request.data
        target = d.get('status')
        org, err = self.ctx(request, 'approve' if target in (PS.APPROVED, PS.SCHEDULED, PS.PUBLISHED) else 'write')
        if err:
            return err
        p = self._get(org, pk)
        if p is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if p.status == PS.PUBLISHED and target != PS.PUBLISHED and any(k in d for k in ('texto', 'titulo')):
            return Response({'detail': 'Conteúdo já publicado não pode ser editado aqui.'}, status=status.HTTP_409_CONFLICT)
        changed = False
        if 'titulo' in d:
            p.title, changed = str(d['titulo'] or '').strip()[:200], True
        if 'texto' in d:
            p.body, changed = str(d['texto'] or '')[:25000], True
        if 'hashtags' in d and isinstance(d['hashtags'], list):
            p.hashtags, changed = [str(t).strip().lstrip('#').replace(' ', '')[:40] for t in d['hashtags'] if str(t).strip()][:8], True
        if 'imagem_url' in d:
            url = str(d['imagem_url'] or '').strip()
            if url and not url.startswith('https://'):
                return Response({'detail': 'A imagem precisa ser uma URL https pública.'}, status=status.HTTP_400_BAD_REQUEST)
            p.image_url = url[:500]
        if 'agendado_para' in d:
            when = parse_datetime(str(d['agendado_para'] or '')) if d['agendado_para'] else None
            if d['agendado_para'] and when is None:
                return Response({'detail': 'Data/hora inválida.'}, status=status.HTTP_400_BAD_REQUEST)
            if when and timezone.is_naive(when):
                when = timezone.make_aware(when)
            p.scheduled_at = when
        if changed:
            p.compliance = compliance.check(p.body + ' ' + ' '.join(p.hashtags or []), self.scope, p.channel)
            if p.status in (PS.APPROVED, PS.SCHEDULED):
                p.status = PS.DRAFT                    # mudou o texto: volta para aprovação
        if target:
            if target not in PS.values or target == PS.FAILED:
                return Response({'detail': 'Situação inválida.'}, status=status.HTTP_400_BAD_REQUEST)
            if target in (PS.APPROVED, PS.SCHEDULED) and compliance.blocking(p.compliance) and d.get('revisei_alertas') is not True:
                return Response({'detail': 'Há alertas de nível alto. Corrija o texto ou confirme que revisou.', 'code': 'compliance'},
                                status=status.HTTP_409_CONFLICT)
            if target == PS.SCHEDULED:
                if not p.scheduled_at or p.scheduled_at < timezone.now() - timedelta(minutes=5):
                    return Response({'detail': 'Escolha data e hora futuras para agendar.'}, status=status.HTTP_400_BAD_REQUEST)
                if p.channel == 'instagram' and not p.image_url:
                    return Response({'detail': 'O Instagram exige uma imagem (URL pública).'}, status=status.HTTP_400_BAD_REQUEST)
            if target in (PS.APPROVED, PS.SCHEDULED) and p.approved_by_id is None:
                p.approved_by = request.user
                services.learn(p, request.user)
            if target == PS.PUBLISHED:
                p.published_at = p.published_at or timezone.now()
                p.publish_error = ''
            if target == PS.DRAFT:
                p.approved_by = None
            p.status = target
        p.save()
        audit.log('marketing.content_updated', actor=request.user, organization=org, target=p, changes={'status': p.status})
        return Response(piece_json(p))

    def delete(self, request, pk):
        org, err = self.ctx(request, 'write')
        if err:
            return err
        p = self._get(org, pk)
        if p is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('marketing.content_deleted', actor=request.user, organization=org, target=p, changes={'canal': p.channel})
        p.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PiecePublishView(PieceDetailView):
    def post(self, request, pk):
        org, err = self.ctx(request, 'approve')
        if err:
            return err
        p = self._get(org, pk)
        if p is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if p.status not in (PS.APPROVED, PS.SCHEDULED, PS.FAILED):
            return Response({'detail': 'Aprove o conteúdo antes de publicar.'}, status=status.HTTP_409_CONFLICT)
        try:
            p = services.publish(p)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(piece_json(p))


class CampaignListView(_Scoped):
    def get(self, request):
        org, err = self.ctx(request)
        if err:
            return err
        return Response([campaign_json(c) for c in self.campaigns(org)])

    def post(self, request):
        org, err = self.ctx(request, 'write')
        if err:
            return err
        d = request.data
        name = str(d.get('nome') or '').strip()
        if not 3 <= len(name) <= 120:
            return Response({'detail': 'Nome da campanha entre 3 e 120 caracteres.'}, status=status.HTTP_400_BAD_REQUEST)
        channels = [c for c in (d.get('canais') or []) if c in ContentPiece.Channel.values]
        c = Campaign.objects.create(scope=self.scope, organization=org, name=name, goal=str(d.get('objetivo') or '')[:300],
                                    audience=str(d.get('publico') or '')[:200], channels=channels, notes=str(d.get('notas') or '')[:3000],
                                    starts_on=parse_date(str(d.get('inicio') or '')), ends_on=parse_date(str(d.get('fim') or '')),
                                    created_by=request.user)
        audit.log('marketing.campaign_saved', actor=request.user, organization=org, target=c, changes={'nome': name})
        return Response(campaign_json(c), status=status.HTTP_201_CREATED)


class CampaignDetailView(_Scoped):
    def delete(self, request, pk):
        org, err = self.ctx(request, 'write')
        if err:
            return err
        deleted, _ = self.campaigns(org).filter(pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


# ----------------------------------------------------------------------------- Gestão Cadrius
IsMarketing = HasArea.of('marketing')


class StaffMixin:
    scope = 'cadrius'
    permission_classes = [permissions.IsAuthenticated, IsMarketing]


class StaffIdeasView(StaffMixin, IdeasView):
    pass


class StaffCheckView(StaffMixin, CheckView):
    pass


class StaffPieceListView(StaffMixin, PieceListView):
    pass


class StaffPieceDetailView(StaffMixin, PieceDetailView):
    pass


class StaffPiecePublishView(StaffMixin, PiecePublishView):
    pass


class StaffCampaignListView(StaffMixin, CampaignListView):
    pass


class StaffCampaignDetailView(StaffMixin, CampaignDetailView):
    pass


class GrowthView(StaffMixin, APIView):
    """Indicadores para a equipe de marketing: cadastros, testes, conversões e cancelamentos por semana."""

    def get(self, request):
        from accounts.models import Organization
        days = 90
        since = timezone.now() - timedelta(days=days)
        orgs = Organization.objects.filter(created_at__gte=since)
        weeks = {}
        for o in orgs.only('created_at', 'subscription_status'):
            wk = timezone.localtime(o.created_at).date()
            wk = (wk - timedelta(days=wk.weekday())).isoformat()
            row = weeks.setdefault(wk, {'semana': wk, 'cadastros': 0, 'pagantes': 0})
            row['cadastros'] += 1
            row['pagantes'] += 1 if o.subscription_status == 'active' else 0
        total = orgs.count()
        paying = orgs.filter(subscription_status='active').count()
        return Response({
            'periodo_dias': days, 'cadastros': total, 'em_teste': orgs.filter(subscription_status='trialing').count(),
            'pagantes': paying, 'conversao_pct': round(100 * paying / total) if total else None,
            'cancelados': orgs.filter(subscription_status='canceled').count(),
            'por_semana': sorted(weeks.values(), key=lambda r: r['semana']),
            'conteudos_publicados': ContentPiece.objects.filter(scope='cadrius', status='publicado', published_at__gte=since).count(),
            'playbook': PLAYBOOK,
        })


PLAYBOOK = [
    {'acao': 'Conteúdo educativo semanal', 'canal': 'LinkedIn + blog', 'por_que': 'Advogados decidem por autoridade e utilidade; '
     'artigos sobre prazos, DJEN e LGPD atraem gestores de escritório pelo Google (SEO).'},
    {'acao': 'Webinars com subseções da OAB e ESA', 'canal': 'Parcerias', 'por_que': 'Público qualificado de jovens advogados; '
     'tema "tecnologia e prazos" sem venda direta.'},
    {'acao': 'Teste grátis com onboarding guiado', 'canal': 'Site + e-mail', 'por_que': 'Converte quem chega pelo conteúdo; '
     'acompanhar a conversão em "Indicadores".'},
    {'acao': 'Programa de indicação', 'canal': 'Clientes atuais', 'por_que': 'Escritórios confiam em colegas; '
     'recompensa em créditos de IA (sem desconto agressivo).'},
    {'acao': 'Vídeos curtos de "antes e depois"', 'canal': 'Instagram/Reels e YouTube Shorts', 'por_que': 'Mostram em 30 s a '
     'leitura de intimação virando prazo na agenda.'},
    {'acao': 'Perfil no Google e avaliações', 'canal': 'Google', 'por_que': 'Busca local por "software jurídico" e prova social.'},
]
