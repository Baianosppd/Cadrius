"""API da caixa de publicações (CAD-173). Prefixo: /api/v1/publications/

Ler: qualquer pessoa do escritório. Confirmar/descartar e consultar agora: dono, administrador e advogado.
Cadastrar/remover OAB acompanhada: dono e administrador."""
from __future__ import annotations

import re

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from core.pii import blind_index
from publications import services
from publications.models import OabWatch, Publication

WRITE_ROLES = MANAGE_TEAM_ROLES | {'MEMBER'}
UFS = {'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS',
       'RO', 'RR', 'SC', 'SP', 'SE', 'TO'}
PAGE = 50


def watch_json(w):
    return {'id': w.pk, 'numero': w.numero, 'uf': w.uf, 'nome': w.nome, 'ativa': w.is_active,
            'responsavel': {'id': str(w.responsavel_id), 'nome': w.responsavel.get_full_name() or w.responsavel.email} if w.responsavel_id else None,
            'ultima_consulta': w.last_checked_at, 'erro': w.last_error}


def pub_json(p, full=False):
    data = {'id': p.pk, 'status': p.status, 'tribunal': p.tribunal, 'tipo': p.tipo, 'orgao': p.orgao, 'classe': p.classe, 'cnj': p.cnj,
            'disponibilizada_em': p.disponibilizada_em, 'publicada_em': p.publicada_em, 'vencimento': p.vencimento,
            'triagem': p.triage, 'oab': str(p.watch) if p.watch_id else '', 'link': p.link,
            'processo': {'id': p.case_id, 'cliente': p.case.client.name if p.case_id and p.case.client_id else None} if p.case_id else None,
            'tarefa_id': p.task_id, 'revisada_em': p.reviewed_at, 'observacao': p.review_note,
            'revisada_por': (p.reviewed_by.get_full_name() or p.reviewed_by.email) if p.reviewed_by_id else None}
    if full:
        data.update(texto=p.texto, partes=p.partes)
    return data


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def membership(self, request, roles=None):
        m = get_active_membership(request.user)
        if m is None:
            return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        if roles is not None and m.role not in roles:
            return None, Response({'detail': 'Seu perfil não permite esta ação.'}, status=status.HTTP_403_FORBIDDEN)
        return m, None


class WatchListView(_Base):
    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        return Response([watch_json(w) for w in OabWatch.objects.filter(organization=m.organization).select_related('responsavel')])

    def post(self, request):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        numero = re.sub(r'\D', '', str(request.data.get('numero', '')))
        uf = str(request.data.get('uf', '')).strip().upper()
        if not 1 <= len(numero) <= 8 or uf not in UFS:
            return Response({'detail': 'Informe o número da OAB (só dígitos) e a UF.'}, status=status.HTTP_400_BAD_REQUEST)
        numero = numero.lstrip('0') or '0'
        if OabWatch.objects.filter(organization=m.organization, numero=numero, uf=uf).exists():
            return Response({'detail': 'Esta OAB já está sendo acompanhada.'}, status=status.HTTP_409_CONFLICT)
        resp = services._member(m.organization, request.data.get('responsavel_id')) or request.user
        w = OabWatch.objects.create(organization=m.organization, numero=numero, uf=uf, nome=str(request.data.get('nome', '')).strip()[:120],
                                    responsavel=resp)
        audit.log('publication.watch_added', actor=request.user, organization=m.organization, target=w, changes={'oab': f'{numero}/{uf}'})
        return Response(watch_json(w), status=status.HTTP_201_CREATED)


class WatchDetailView(_Base):
    def _get(self, m, pk):
        return OabWatch.objects.filter(organization=m.organization, pk=pk).select_related('responsavel').first()

    def patch(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        w = self._get(m, pk)
        if w is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if 'ativa' in request.data:
            w.is_active = request.data['ativa'] is not False
        if 'responsavel_id' in request.data:
            w.responsavel = services._member(m.organization, request.data.get('responsavel_id')) or w.responsavel
        if 'nome' in request.data:
            w.nome = str(request.data.get('nome') or '').strip()[:120]
        w.save()
        return Response(watch_json(w))

    def delete(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        w = self._get(m, pk)
        if w is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('publication.watch_removed', actor=request.user, organization=m.organization, target=w, changes={'oab': str(w)})
        w.delete()                                       # as publicações já capturadas ficam na caixa
        return Response(status=status.HTTP_204_NO_CONTENT)


class WatchCheckNowView(WatchDetailView):
    def post(self, request, pk):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        w = self._get(m, pk)
        if w is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response({**services.poll_watch(w), 'oab': watch_json(w)})


class PublicationListView(_Base):
    """GET ?status=nova|confirmada|descartada&cnj=…&pagina=1 — mais recentes primeiro; ``contagem`` por situação."""

    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        base = Publication.objects.filter(organization=m.organization)
        qs = base.select_related('watch', 'case__client', 'reviewed_by')
        st = request.query_params.get('status', Publication.Status.NEW)
        if st in Publication.Status.values:
            qs = qs.filter(status=st)
        if request.query_params.get('cnj'):
            qs = qs.filter(cnj_bidx=blind_index('case.cnj', request.query_params['cnj'], 'digits') or '-')
        if request.query_params.get('tribunal'):
            qs = qs.filter(tribunal__iexact=request.query_params['tribunal'])
        try:
            page = max(1, int(request.query_params.get('pagina', 1)))
        except ValueError:
            page = 1
        total = qs.count()
        counts = {s: base.filter(status=s).count() for s in Publication.Status.values}
        return Response({'total': total, 'pagina': page, 'contagem': counts,
                         'resultados': [pub_json(p) for p in qs[(page - 1) * PAGE: page * PAGE]]})


class PublicationDetailView(_Base):
    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        p = Publication.objects.filter(organization=m.organization, pk=pk).select_related('watch', 'case__client', 'reviewed_by').first()
        if p is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('data.read', actor=request.user, organization=m.organization, target=p, data_categories=['dados_processuais'])
        return Response(pub_json(p, full=True))


class PublicationActionView(_Base):
    action = 'confirm'

    def post(self, request, pk):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        p = Publication.objects.filter(organization=m.organization, pk=pk).select_related('watch__responsavel', 'case__client').first()
        if p is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        d = request.data
        try:
            if self.action == 'confirm':
                p = services.confirm(p, request.user, prazo_dias=d.get('prazo_dias'), vencimento=d.get('vencimento'),
                                     responsavel_id=d.get('responsavel_id'), acompanhar=d.get('acompanhar') is True,
                                     note=str(d.get('observacao', '')))
            elif self.action == 'discard':
                p = services.discard(p, request.user, str(d.get('motivo', '')))
            else:
                p = services.reopen(p, request.user)
        except services.ReviewError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT if 'já' in str(exc) else status.HTTP_400_BAD_REQUEST)
        return Response(pub_json(p, full=True))


class PrazoPreviewView(_Base):
    """GET <id>/prazo/?dias=15 → vencimento recalculado (para o advogado ajustar antes de confirmar)."""

    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        p = Publication.objects.filter(organization=m.organization, pk=pk).first()
        if p is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            dias = int(request.query_params.get('dias', ''))
            if not 1 <= dias <= 365:
                raise ValueError
        except ValueError:
            return Response({'detail': 'Prazo entre 1 e 365 dias úteis.'}, status=status.HTTP_400_BAD_REQUEST)
        publicada, venc = services.compute_dates(p, dias)
        return Response({'publicada_em': publicada, 'vencimento': venc, 'dias': dias})
