"""E-mail profissional (CAD-226): assinatura de cada pessoa, visual do escritório e prévia."""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from audit import service as audit
from integrations import email_layout

MANAGE = {'OWNER', 'ADMIN'}
SAMPLE = ('Olá, Maria!\n\nPassando para avisar que a audiência do seu processo foi marcada para 12/11, às 14h, no Fórum '
          'Central. Leve um documento com foto e chegue 30 minutos antes.\n\nQualquer dúvida, é só responder este e-mail.\n\n'
          'Um abraço,')


def _org(request):
    m = get_active_membership(request.user)
    return (m.organization, m) if m else (None, None)


class SignatureView(APIView):
    """GET/PUT a assinatura de e-mail da própria pessoa: {texto, imagem (data URL PNG/JPG até 200 KB ou "")}."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response({'texto': u.email_signature or '', 'imagem': u.email_signature_image or ''})

    def put(self, request):
        u = request.user
        text = str(request.data.get('texto') or '').strip()[:600]
        image = str(request.data.get('imagem') or '').strip()
        try:
            email_layout.decode_image(image)
        except email_layout.SignatureError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        u.email_signature, u.email_signature_image = text, image
        u.save(update_fields=['email_signature', 'email_signature_image'])
        audit.log('user.updated', actor=u, changes={'fields': ['email_signature']}, data_categories=['identificacao'],
                  legal_basis='contrato')
        return self.get(request)


class VisualView(APIView):
    """GET visuais + o do escritório. PUT (dono/admin) {visual, cor}."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        org, m = _org(request)
        if org is None:
            return Response({'detail': 'Sem escritório ativo.'}, status=status.HTTP_403_FORBIDDEN)
        layout, color = email_layout.office_style(org)
        from brain import profile
        return Response({'visual': layout, 'cor': color, 'pode_editar': m.role in MANAGE, 'logo': profile.get(org).email_logo or '',
                         'opcoes': [{'id': k, 'label': v} for k, v in email_layout.LAYOUTS.items()]})

    def put(self, request):
        from brain import profile
        org, m = _org(request)
        if org is None or m.role not in MANAGE:
            return Response({'detail': 'Só dono ou administrador muda o visual do escritório.'}, status=status.HTTP_403_FORBIDDEN)
        p = profile.get(org)
        layout = request.data.get('visual', p.email_layout or email_layout.DEFAULT_LAYOUT)
        color = str(request.data.get('cor', p.brand_color or email_layout.DEFAULT_COLOR) or '')
        if layout not in email_layout.LAYOUTS or not email_layout.COLOR_RX.match(color):
            return Response({'detail': 'Escolha um visual da lista e uma cor no formato #RRGGBB.'}, status=status.HTTP_400_BAD_REQUEST)
        fields = ['email_layout', 'brand_color', 'updated_at']
        if 'logo' in request.data:                       # CAD-231: logo da empresa ("" remove)
            logo = str(request.data.get('logo') or '').strip()
            try:
                email_layout.decode_image(logo, 'da logo')
            except email_layout.SignatureError as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            p.email_logo = logo
            fields.append('email_logo')
        p.email_layout, p.brand_color = layout, color
        p.save(update_fields=fields)
        audit.log('brain.profile_updated', actor=request.user, organization=org, target=p, changes={'campos': ['email_visual']})
        return self.get(request)


class PreviewView(APIView):
    """POST {assunto, mensagem, visual} → {html} com a assinatura de quem pede (mostrada num iframe isolado)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        org, _ = _org(request)
        if org is None:
            return Response({'detail': 'Sem escritório ativo.'}, status=status.HTTP_403_FORBIDDEN)
        body = str(request.data.get('mensagem') or '').strip()[:4000] or SAMPLE
        r = email_layout.render(org, str(request.data.get('assunto') or 'Prévia')[:150], body, user=request.user,
                                layout=str(request.data.get('visual') or ''))
        html = r['html']
        if r['image']:                     # na prévia a imagem vai embutida (no e-mail real vai como anexo CID)
            html = html.replace(f'cid:{email_layout.SIGNATURE_CID}', request.user.email_signature_image)
        if r.get('logo'):
            from brain import profile
            html = html.replace(f'cid:{email_layout.LOGO_CID}', profile.get(org).email_logo)
        return Response({'html': html})
