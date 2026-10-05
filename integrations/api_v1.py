"""API das integrações (CAD-174). Prefixo: /api/v1/integrations/

catalog/ (todos), connections/<id>/test/ (membros, não leitura), signature/ (ZapSign: documento PDF → assinatura),
charge/ (Asaas: cobrança para um contato). Envio de assinatura e cobrança: dono, administrador e advogado."""
from __future__ import annotations

from datetime import date

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from integrations import services
from integrations.catalog import CATEGORIES, public_catalog

WRITE_ROLES = MANAGE_TEAM_ROLES | {'MEMBER'}


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def membership(self, request, roles=None):
        m = get_active_membership(request.user)
        if m is None:
            return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        if roles is not None and m.role not in roles:
            return None, Response({'detail': 'Seu perfil não permite esta ação.'}, status=status.HTTP_403_FORBIDDEN)
        return m, None


class CatalogView(_Base):
    def get(self, request):
        _, err = self.membership(request)
        return err or Response({'categorias': CATEGORIES, 'apps': public_catalog()})


class TestConnectionView(_Base):
    def post(self, request, pk):
        from integrations.models import AppConnection
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        member_ids = m.organization.members.filter(is_active=True).values_list('user_id', flat=True)
        conn = AppConnection.objects.filter(pk=pk, user_id__in=member_ids).first()
        if conn is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            msg, ok = services.test_connection(conn), True
        except services.IntegrationError as exc:
            msg, ok = str(exc), False
        audit.log('connection.tested', actor=request.user, organization=m.organization, target=conn,
                  changes={'app': conn.app_name, 'ok': ok})
        return Response({'ok': ok, 'mensagem': msg})


class SignatureView(_Base):
    """POST {documento_id, signatarios: [contato_id…]} → envia o PDF para assinatura no ZapSign."""

    def post(self, request):
        from contacts.models import Contact
        from documents.models import Document
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        conn = services.org_connection(m.organization, 'ZAPSIGN')
        if conn is None:
            return Response({'detail': 'Conecte o ZapSign em Integrações primeiro.', 'code': 'not_connected'}, status=status.HTTP_409_CONFLICT)
        doc = Document.objects.filter(organization=m.organization, pk=request.data.get('documento_id')).first()
        if doc is None or not doc.arquivo:
            return Response({'detail': 'Documento não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        ids = request.data.get('signatarios') if isinstance(request.data.get('signatarios'), list) else []
        contacts = list(Contact.objects.filter(organization=m.organization, pk__in=ids[:10]))
        if not contacts:
            return Response({'detail': 'Escolha ao menos um signatário do quadro de contatos.'}, status=status.HTTP_400_BAD_REQUEST)
        if any(not (c.email or c.phone) for c in contacts):
            return Response({'detail': 'Todo signatário precisa de e-mail ou telefone.'}, status=status.HTTP_400_BAD_REQUEST)
        with doc.arquivo.open('rb') as fh:
            data = fh.read()
        if not data.startswith(b'%PDF'):
            return Response({'detail': 'Só PDFs podem ir para assinatura.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = services.zapsign_send(conn.credentials or {}, name=doc.nome, pdf=data,
                                           signers=[{'nome': c.name, 'email': c.email, 'telefone': c.phone} for c in contacts])
        except services.IntegrationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        audit.log('signature.requested', actor=request.user, organization=m.organization, target=doc,
                  changes={'provedor': 'zapsign', 'signatarios': len(contacts)}, data_categories=['identificacao', 'contato'],
                  legal_basis='execucao_contrato')
        return Response(result, status=status.HTTP_201_CREATED)


class ChargeView(_Base):
    """POST {contato_id, valor, vencimento (AAAA-MM-DD), descricao, forma: BOLETO|PIX|UNDEFINED} → cobrança no Asaas."""

    def post(self, request):
        from contacts.models import Contact
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        conn = services.org_connection(m.organization, 'ASAAS')
        if conn is None:
            return Response({'detail': 'Conecte o Asaas em Integrações primeiro.', 'code': 'not_connected'}, status=status.HTTP_409_CONFLICT)
        d = request.data
        contact = Contact.objects.filter(organization=m.organization, pk=d.get('contato_id')).first()
        if contact is None:
            return Response({'detail': 'Contato não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            value = round(float(str(d.get('valor', '')).replace(',', '.')), 2)
            due = date.fromisoformat(str(d.get('vencimento', '')))
        except ValueError:
            return Response({'detail': 'Informe o valor e o vencimento (AAAA-MM-DD).'}, status=status.HTTP_400_BAD_REQUEST)
        if not 5 <= value <= 1_000_000:
            return Response({'detail': 'Valor entre R$ 5,00 e R$ 1.000.000,00.'}, status=status.HTTP_400_BAD_REQUEST)
        if due < date.today():
            return Response({'detail': 'O vencimento não pode estar no passado.'}, status=status.HTTP_400_BAD_REQUEST)
        forma = d.get('forma') if d.get('forma') in ('BOLETO', 'PIX', 'UNDEFINED') else 'UNDEFINED'
        try:
            result = services.asaas_charge(conn.credentials or {}, contact=contact, value=value, due_date=due,
                                           description=str(d.get('descricao') or 'Honorários advocatícios'), billing_type=forma)
        except services.IntegrationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        audit.log('billing.charge_created', actor=request.user, organization=m.organization, target=contact,
                  changes={'provedor': 'asaas', 'valor': value, 'forma': forma}, data_categories=['identificacao', 'financeiro'],
                  legal_basis='execucao_contrato')
        from carteira.models import Receivable          # CAD-175: a cobrança entra no financeiro e recebe baixa pelo webhook
        rec = Receivable.objects.create(organization=m.organization, contact=contact, description=str(d.get('descricao') or 'Honorários advocatícios')[:200],
                                        amount_cents=int(round(value * 100)), due_date=due, asaas_id=str(result.get('id') or '')[:40],
                                        payment_url=(result.get('link') or result.get('boleto') or '')[:500], created_by=request.user)
        return Response({**result, 'lancamento_id': rec.pk}, status=status.HTTP_201_CREATED)
