"""E-mail com visual profissional e assinatura (CAD-226).

Todo e-mail que o Cadrius manda em nome do escritório (regras, assistente, fluxos, portal) passa por aqui:
- o texto continua indo como texto puro (leitores simples e filtros de spam gostam disso);
- junto vai a versão HTML num dos visuais ("moderno", "clássico", "simples"), com a cor do escritório;
- no fim entra a assinatura de quem enviou (perfil da pessoa) ou, sem ela, a do escritório (Perfil do escritório).
  A imagem da assinatura (manuscrita ou logo) vai anexada como imagem embutida (CID), que os clientes de e-mail exibem
  sem pedir para "carregar imagens".

O texto vem do escritório ou da IA: tudo é escapado; só links http(s) viram âncoras.
"""
from __future__ import annotations

import base64
import binascii
import html
import re
from email.mime.image import MIMEImage

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

LAYOUTS = {
    'moderno': 'Moderno (faixa com a cor do escritório)',
    'classico': 'Clássico (sóbrio, com serifa)',
    'simples': 'Simples (só o texto e a assinatura)',
}
DEFAULT_LAYOUT = 'moderno'
DEFAULT_COLOR = '#1d4ed8'
COLOR_RX = re.compile(r'^#[0-9a-fA-F]{6}$')
IMAGE_RX = re.compile(r'^data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)$')
MAX_IMAGE_BYTES = 200 * 1024
URL_RX = re.compile(r'(https?://[^\s<>"\']+)')
SIGNATURE_CID = 'assinatura-cadrius'
LOGO_CID = 'logo-escritorio'


class SignatureError(ValueError):
    pass


def decode_image(data_url: str, what: str = 'da assinatura') -> tuple[bytes, str] | None:
    """data:image/png;base64,... → (bytes, 'png'|'jpeg'). Levanta SignatureError se inválida ou grande demais."""
    if not data_url:
        return None
    m = IMAGE_RX.match(data_url.strip())
    if not m:
        raise SignatureError(f'A imagem {what} precisa ser PNG ou JPG.')
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError(f'Imagem {what} ilegível.') from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise SignatureError(f'A imagem {what} deve ter até 200 KB.')
    magic_ok = raw.startswith(b'\x89PNG') if m.group(1) == 'png' else raw.startswith(b'\xff\xd8')
    if not magic_ok:
        raise SignatureError('O arquivo não é uma imagem PNG/JPG válida.')
    return raw, m.group(1)


def office_logo(org):
    """CAD-231: logo da empresa (bytes, subtipo) ou None."""
    from brain.models import OfficeProfile
    p = OfficeProfile.objects.filter(organization=org).only('email_logo').first()
    try:
        return decode_image(p.email_logo if p else '', 'da logo')
    except SignatureError:
        return None


def office_style(org) -> tuple[str, str]:
    from brain.models import OfficeProfile
    p = OfficeProfile.objects.filter(organization=org).only('email_layout', 'brand_color').first()
    layout = (p.email_layout if p else '') or DEFAULT_LAYOUT
    color = (p.brand_color if p else '') or DEFAULT_COLOR
    return (layout if layout in LAYOUTS else DEFAULT_LAYOUT), (color if COLOR_RX.match(color) else DEFAULT_COLOR)


def signature_for(org, user=None) -> tuple[str, tuple[bytes, str] | None]:
    """Assinatura de quem envia; sem ela, a do escritório; sem as duas, o nome do escritório."""
    text, image = '', None
    if user is not None:
        text = (getattr(user, 'email_signature', '') or '').strip()
        try:
            image = decode_image(getattr(user, 'email_signature_image', '') or '')
        except SignatureError:
            image = None
    if not text:
        from brain.models import OfficeProfile
        p = OfficeProfile.objects.filter(organization=org).only('signature').first()
        text = (p.signature if p else '').strip() or str(org)
    return text, image


def _paragraphs(text: str) -> str:
    out = []
    for block in re.split(r'\n\s*\n', (text or '').strip()):
        safe = html.escape(block)
        safe = URL_RX.sub(lambda m: f'<a href="{m.group(1)}" style="color:inherit">{m.group(1)}</a>', safe)
        out.append(f'<p style="margin:0 0 14px">{safe.replace(chr(10), "<br>")}</p>')
    return ''.join(out)


def render(org, subject: str, body: str, *, user=None, layout: str = '', footer: str = '') -> dict:
    """Devolve {'text', 'html', 'image', 'logo'} — imagens como (bytes, subtipo) para anexar como CID, ou None."""
    office_layout, color = office_style(org)
    layout = layout if layout in LAYOUTS else office_layout
    sig_text, image = signature_for(org, user)
    logo = office_logo(org)
    text = f'{body.strip()}\n\n{sig_text}' + (f'\n\n{footer.strip()}' if footer else '')

    font = "Georgia, 'Times New Roman', serif" if layout == 'classico' else "-apple-system, 'Segoe UI', Roboto, Arial, sans-serif"
    sig_html = f'<div style="margin-top:20px;padding-top:14px;border-top:1px solid #e5e7eb;color:#374151;font-size:14px">' \
               f'{html.escape(sig_text).replace(chr(10), "<br>")}' + \
               (f'<div style="margin-top:10px"><img src="cid:{SIGNATURE_CID}" alt="Assinatura" style="max-width:220px;max-height:90px"></div>'
                if image else '') + '</div>'
    foot_html = f'<p style="margin:18px 0 0;color:#6b7280;font-size:12px">{html.escape(footer.strip())}</p>' if footer else ''
    office = html.escape(str(org))
    logo_img = (f'<img src="cid:{LOGO_CID}" alt="{office}" style="max-height:44px;max-width:180px;vertical-align:middle;'
                f'border:0">') if logo else ''
    if layout == 'simples':
        header = f'<div style="padding:0 4px 12px">{logo_img}</div>' if logo else ''
    elif layout == 'classico':
        header = (f'<div style="padding:20px 28px 12px;text-align:center;border-bottom:2px solid {color};font-family:{font};'
                  f'font-size:20px;letter-spacing:.5px;color:#111827">'
                  + (f'<div style="margin-bottom:8px">{logo_img}</div>' if logo else '') + f'{office}</div>')
    else:
        # logo sobre um "selo" branco, legível em qualquer cor de faixa
        badge = (f'<span style="display:inline-block;background:#ffffff;border-radius:8px;padding:6px 10px;margin-right:12px;'
                 f'vertical-align:middle">{logo_img}</span>') if logo else ''
        header = (f'<div style="background:{color};padding:18px 28px;color:#ffffff;font-size:18px;font-weight:600;'
                  f'border-radius:10px 10px 0 0">{badge}<span style="vertical-align:middle">{office}</span></div>')
    radius = '0 0 10px 10px' if layout == 'moderno' else '10px'
    page = (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{html.escape(subject)}</title></head>'
        f'<body style="margin:0;padding:24px 12px;background:#f3f4f6;font-family:{font};color:#111827">'
        '<div style="max-width:620px;margin:0 auto">'
        f'{header}<div style="background:#ffffff;padding:26px 28px;border-radius:{radius};border:1px solid #e5e7eb;'
        f'font-size:15px;line-height:1.6">{_paragraphs(body)}{sig_html}{foot_html}</div>'
        '</div></body></html>'
    )
    return {'text': text, 'html': page, 'image': image, 'logo': logo}


def build_message(org, subject: str, body: str, to: list, *, sender: str, user=None, layout: str = '', footer: str = '',
                  connection=None) -> EmailMultiAlternatives:
    r = render(org, subject, body, user=user, layout=layout, footer=footer)
    msg = EmailMultiAlternatives(subject, r['text'], sender, to, connection=connection)
    msg.attach_alternative(r['html'], 'text/html')
    for key, cid, name in (('image', SIGNATURE_CID, 'assinatura'), ('logo', LOGO_CID, 'logo')):
        if r.get(key):
            msg.mixed_subtype = 'related'
            img = MIMEImage(r[key][0], _subtype=r[key][1])
            img.add_header('Content-ID', f'<{cid}>')
            img.add_header('Content-Disposition', 'inline', filename=f'{name}.{"png" if r[key][1] == "png" else "jpg"}')
            msg.attach(img)
    return msg


def send(org, subject: str, body: str, to: list, *, user=None, layout: str = '', footer: str = '') -> str:
    """Envia pelo SMTP do escritório (se houver) ou pelo remetente do Cadrius. Devolve 'escritorio' ou 'cadrius'."""
    from integrations.services import office_sender
    office = office_sender(org)
    if office is not None:
        sender, connection = office
        build_message(org, subject, body, to, sender=sender, user=user, layout=layout, footer=footer,
                      connection=connection).send(fail_silently=False)
        return 'escritorio'
    build_message(org, subject, body, to, sender=settings.DEFAULT_FROM_EMAIL, user=user, layout=layout,
                  footer=footer).send(fail_silently=False)
    return 'cadrius'
