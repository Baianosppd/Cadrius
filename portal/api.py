"""Portal do cliente (CAD-175). Prefixo: /api/v1/portal/

Equipe (autenticada): ``links/`` lista/cria links de um contato; ``links/<id>/revogar/``.
Cliente (público, só com o token): ``acesso/<token>/`` — processos, andamentos em linguagem simples e honorários em aberto.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from audit import service as audit
from contacts.models import Contact
from portal.models import PortalLink
from portal.plain import explain

WRITE_ROLES = {'OWNER', 'ADMIN', 'MEMBER'}
DEFAULT_DAYS, MAX_DAYS = 90, 365
MAX_ACTIVE_PER_CONTACT = 3
MOVEMENTS_PER_CASE = 15


def token_hash(token: str) -> str:
    return hashlib.sha256((token or '').encode()).hexdigest()


def portal_url(token: str) -> str:
    return f'{settings.FRONTEND_URL}/portal/{token}'


def link_json(link: PortalLink) -> dict:
    now = timezone.now()
    state = 'revogado' if link.revoked_at else ('expirado' if link.expires_at <= now else 'ativo')
    return {'id': link.pk, 'contato_id': link.contact_id, 'final': link.hint, 'mostra_financeiro': link.show_finance,
            'expira_em': link.expires_at, 'situacao': state, 'acessos': link.access_count, 'ultimo_acesso': link.last_access_at,
            'criado_em': link.created_at, 'criado_por': link.created_by.email if link.created_by_id else ''}


def _bad(msg, code=status.HTTP_400_BAD_REQUEST):
    return Response({'detail': msg}, status=code)


class LinksView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _m(self, request, write=False):
        m = get_active_membership(request.user)
        if m is None or (write and m.role not in WRITE_ROLES):
            return None
        return m

    def get(self, request):
        m = self._m(request)
        if m is None:
            return _bad('Sem permissão.', status.HTTP_403_FORBIDDEN)
        qs = PortalLink.objects.filter(organization=m.organization).select_related('created_by')
        if request.query_params.get('contato'):
            qs = qs.filter(contact_id=request.query_params['contato'])
        return Response([link_json(x) for x in qs[:100]])

    def post(self, request):
        """{contato_id, dias?, mostrar_financeiro?, enviar_email?} → devolve o link UMA vez (só o hash fica guardado)."""
        m = self._m(request, write=True)
        if m is None:
            return _bad('Seu perfil não permite criar links do portal.', status.HTTP_403_FORBIDDEN)
        d = request.data
        contact = Contact.objects.filter(organization=m.organization, pk=d.get('contato_id')).first()
        if contact is None:
            return _bad('Contato não encontrado.', status.HTTP_404_NOT_FOUND)
        if contact.kind != Contact.Kind.CLIENT:
            return _bad('O portal é só para contatos do tipo Cliente.')
        try:
            days = int(d.get('dias') or DEFAULT_DAYS)
        except (TypeError, ValueError):
            return _bad('Validade em dias inválida.')
        if not 1 <= days <= MAX_DAYS:
            return _bad(f'Validade entre 1 e {MAX_DAYS} dias.')
        now = timezone.now()
        active = PortalLink.objects.filter(organization=m.organization, contact=contact, revoked_at__isnull=True, expires_at__gt=now)
        if active.count() >= MAX_ACTIVE_PER_CONTACT:
            return _bad(f'Este cliente já tem {MAX_ACTIVE_PER_CONTACT} links ativos. Revogue um antes de criar outro.')
        token = secrets.token_urlsafe(32)
        link = PortalLink.objects.create(organization=m.organization, contact=contact, token_hash=token_hash(token), hint=token[-4:],
                                         show_finance=bool(d.get('mostrar_financeiro', True)), expires_at=now + timedelta(days=days),
                                         created_by=request.user)
        url = portal_url(token)
        sent = ''
        if d.get('enviar_email'):
            if not contact.can_receive('email'):
                sent = 'sem_consentimento'
            else:
                from integrations.services import send_office_email
                subject = f'{m.organization}: acompanhe seu processo'
                body = (f'Olá, {contact.name.split()[0]}!\n\nPreparamos um acesso para você acompanhar seu(s) processo(s) e honorários:\n'
                        f'{url}\n\nO link é pessoal, vale até {timezone.localtime(link.expires_at):%d/%m/%Y} e não deve ser '
                        f'compartilhado.\n\n{m.organization}')
                try:
                    if not send_office_email(m.organization, subject, body, [contact.email]):
                        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [contact.email])
                    sent = 'email'
                except Exception:  # noqa: BLE001 — o link existe; a equipe pode copiar e enviar
                    sent = 'falhou'
        audit.log('portal.link_created', actor=request.user, organization=m.organization, target=contact,
                  changes={'dias': days, 'financeiro': link.show_finance, 'envio': sent or 'copiado'},
                  data_categories=['identificacao', 'processual'], legal_basis='execucao_contrato')
        return Response({**link_json(link), 'url': url, 'envio': sent}, status=status.HTTP_201_CREATED)


class RevokeView(LinksView):
    def post(self, request, pk):
        m = self._m(request, write=True)
        if m is None:
            return _bad('Sem permissão.', status.HTTP_403_FORBIDDEN)
        link = PortalLink.objects.filter(organization=m.organization, pk=pk).first()
        if link is None:
            return _bad('Link não encontrado.', status.HTTP_404_NOT_FOUND)
        if not link.revoked_at:
            link.revoked_at = timezone.now()
            link.save(update_fields=['revoked_at'])
            audit.log('portal.link_revoked', actor=request.user, organization=m.organization, target=link.contact)
        return Response(link_json(link))


class PortalThrottle(AnonRateThrottle):
    rate = '30/min'


class AccessView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [PortalThrottle]

    def get(self, request, token):
        if not 20 <= len(token or '') <= 100:
            return _bad('Link inválido.', status.HTTP_404_NOT_FOUND)
        link = PortalLink.objects.filter(token_hash=token_hash(token)).select_related('organization', 'contact').first()
        now = timezone.now()
        if link is None or link.revoked_at or link.expires_at <= now or not link.organization.is_active:
            return _bad('Este link não é válido ou expirou. Peça um novo ao escritório.', status.HTTP_404_NOT_FOUND)
        PortalLink.objects.filter(pk=link.pk).update(access_count=link.access_count + 1, last_access_at=now)
        if cache.add(f'portal:viewed:{link.pk}', 1, 3600):              # audita no máximo 1 acesso por hora por link
            audit.log('portal.viewed', organization=link.organization, target=link.contact, actor_type='anonymous',
                      actor_label='cliente (portal)', data_categories=['processual'], legal_basis='execucao_contrato')
        return Response(payload(link))


def payload(link: PortalLink) -> dict:
    contact, org = link.contact, link.organization
    cases = []
    for case in contact.cases.filter(organization=org, is_active=True).order_by('-last_movement_at'):
        moves = []
        for mv in case.movements.all()[:MOVEMENTS_PER_CASE]:
            text, known = explain(mv.name, mv.complement)
            moves.append({'data': mv.occurred_at, 'explicacao': text, 'reconhecido': known, 'original': mv.name})
        cases.append({'cnj': case.cnj, 'tribunal': case.tribunal.upper(), 'ultima_movimentacao': case.last_movement_at, 'andamentos': moves})
    data = {'escritorio': str(org), 'cliente': contact.name.split()[0] if contact.name else '', 'processos': cases,
            'valido_ate': link.expires_at, 'atualizado_em': timezone.now()}
    if link.show_finance:
        from carteira.models import Receivable
        today = timezone.localdate()
        data['honorarios'] = [{'descricao': r.description, 'valor_centavos': r.amount_cents, 'vencimento': r.due_date,
                               'vencido': r.due_date < today, 'link_pagamento': r.payment_url}
                              for r in Receivable.objects.filter(organization=org, contact=contact, status='aberto').order_by('due_date')[:24]]
    return data
