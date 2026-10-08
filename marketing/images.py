"""Imagem para o conteúdo de marketing (CAD-226, revisto no CAD-231).

1. **Arte pronta da marca** (todos os planos, sem IA e sem custo): modelos 1080×1080 com a cor e a logo do escritório:
   ``destaque`` (fundo na cor da marca), ``citacao`` (fundo claro, frase em destaque), ``dica`` (faixa "Dica") e ``foto``
   (uma foto que o escritório subiu, com o título por cima).
2. **Foto do escritório** (todos os planos): usar uma imagem enviada direto como imagem do post.
3. **IA de imagem** (adicional "Estúdio de mídia com IA", incluído no Enterprise): Gemini ``gemini-2.5-flash-image``
   ("Nano Banana"), centralizado no Gemini. Aceita até 3 fotos do escritório como referência (ex.: a fachada, a equipe),
   para a imagem sair fiel. Regras da OAB no prompt (sobriedade, nada de promessa, nenhum dado de cliente). Cobra o peso
   "Imagem de marketing" em créditos, só quando a imagem é entregue.

A imagem fica no armazenamento do Cadrius e ganha um link público assinado (o Instagram exige URL pública para publicar).
"""
from __future__ import annotations

import base64
import io
import logging
import os
import uuid

import requests
from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

SALT = 'cadrius.marketing.image'
TIMEOUT = 120
GEMINI_MODEL_ENV = 'MARKETING_IMAGE_GEMINI_MODEL'
MAX_REFS = 3
STYLES = ('destaque', 'citacao', 'dica', 'foto')
STYLE = ('Fotografia ou ilustração editorial profissional para rede social de escritório de advocacia brasileiro, sóbria e '
         'elegante, luz natural, sem logotipos de terceiros, sem pessoas famosas, sem símbolos de dinheiro ou ostentação, '
         'sem texto escrito na imagem. Formato quadrado.')
ADDON_MSG = ('Gerar imagem e vídeo com IA faz parte do adicional "Estúdio de mídia com IA" (incluído no plano Enterprise). '
             'Sem ele, use as artes prontas da marca ou suas próprias fotos.')


class ImageError(Exception):
    """Mensagem pronta para a tela."""


class AddonRequired(ImageError):
    """O escritório não tem o adicional de mídia com IA."""


def _key(env: str) -> str:
    return (os.environ.get(env) or getattr(settings, env, '') or '').strip()


def providers(org=None) -> list[str]:
    """IA de imagem disponível para o escritório: só o Gemini (CAD-231), se configurado e permitido pela política."""
    from aigov.guard import get_policy, global_ai_enabled
    if not global_ai_enabled() or not _key('GEMINI_API_KEY'):
        return []
    allowed = set(get_policy(org).allowed_providers or []) if org is not None else set()
    return ['GEMINI'] if not allowed or 'GEMINI' in allowed else []


def require_addon(org):
    """Escritório sem o adicional não gera mídia com IA (a Gestão Cadrius, org=None, sempre pode)."""
    from billing import addons
    if org is not None and not addons.media_ai_enabled(org):
        raise AddonRequired(ADDON_MSG)


def prompt_for(piece, with_refs: bool = False) -> str:
    hint = (piece.image_hint or '').strip() or f'Imagem que represente o tema "{piece.theme}"'
    refs = ('\nUse as fotos anexadas como referência fiel (lugar, pessoas e objetos como aparecem nelas); não invente '
            'marcas nem textos.' if with_refs else '')
    return f'{STYLE}\nCena: {hint[:400]}\nTema do post: {piece.theme[:150]}{refs}'


def _inline(data: bytes) -> dict:
    mime = 'image/png' if data.startswith(b'\x89PNG') else 'image/jpeg'
    return {'inlineData': {'mimeType': mime, 'data': base64.b64encode(data).decode()}}


def _gemini(prompt: str, refs: list[bytes] | None = None) -> bytes:
    model = _key(GEMINI_MODEL_ENV) or 'gemini-2.5-flash-image'
    parts = [_inline(r) for r in (refs or [])[:MAX_REFS]] + [{'text': prompt}]
    resp = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', timeout=TIMEOUT,
                         headers={'x-goog-api-key': _key('GEMINI_API_KEY')},
                         json={'contents': [{'parts': parts}], 'generationConfig': {'responseModalities': ['IMAGE']}})
    if resp.status_code >= 400:
        raise ImageError(f'Gemini recusou a imagem ({resp.status_code}).')
    for cand in resp.json().get('candidates') or []:
        for part in (cand.get('content') or {}).get('parts') or []:
            data = (part.get('inlineData') or part.get('inline_data') or {}).get('data')
            if data:
                return base64.b64decode(data)
    raise ImageError('Gemini não devolveu imagem.')


# ----------------------------------------------------------------------------- artes prontas (sem IA)
def _font(px, serif=True):
    from PIL import ImageFont
    names = (('DejaVuSerif-Bold.ttf', 'DejaVuSans-Bold.ttf') if serif else ('DejaVuSans-Bold.ttf', 'DejaVuSerif-Bold.ttf'))
    for name in names:
        path = f'/usr/share/fonts/truetype/dejavu/{name}'
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default(size=px)


def _rgb(color: str) -> tuple[int, int, int]:
    c = (color or '#1d4ed8').lstrip('#')
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (29, 78, 216)


def _mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _wrap(draw, text, font, width_px, max_lines):
    words, lines, line = (text or '').split(), [], ''
    for w in words:
        trial = f'{line} {w}'.strip()
        if draw.textlength(trial, font=font) <= width_px:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip('.,;:') + '…'
    return lines


def _fit_title(draw, title, width_px, max_lines, sizes=(76, 68, 60, 52, 46), serif=True):
    for px in sizes:
        f = _font(px, serif)
        lines = _wrap(draw, title, f, width_px, max_lines + 1)
        if len(lines) <= max_lines:
            return f, lines, px
    f = _font(sizes[-1], serif)
    return f, _wrap(draw, title, f, width_px, max_lines), sizes[-1]


def _paste_logo(img, logo: bytes | None, box, anchor='left'):
    """Cola a logo do escritório (Perfil → assinatura) dentro de ``box`` (x, y, w, h)."""
    if not logo:
        return False
    from PIL import Image
    try:
        mark = Image.open(io.BytesIO(logo)).convert('RGBA')
    except Exception:  # noqa: BLE001 — logo inválida não derruba a arte
        return False
    x, y, w, h = box
    mark.thumbnail((w, h), Image.LANCZOS)
    px = x if anchor == 'left' else x + (w - mark.width) // 2
    img.paste(mark, (px, y + (h - mark.height) // 2), mark)
    return True


def brand_card(title: str, office: str, color: str = '#1d4ed8', *, style: str = 'destaque', photo: bytes | None = None,
               logo: bytes | None = None) -> bytes:
    """Arte pronta da marca, sem IA (1080×1080)."""
    from PIL import Image, ImageDraw, ImageOps
    size, pad = 1080, 96
    base = _rgb(color)
    dark, light = _mix(base, (10, 15, 30), .45), _mix(base, (255, 255, 255), .92)
    title = (title or '').strip() or 'Conteúdo jurídico'
    office = (office or '')[:48]
    style = style if style in STYLES else 'destaque'
    if style == 'foto' and not photo:
        style = 'destaque'

    if style == 'foto':
        img = ImageOps.fit(Image.open(io.BytesIO(photo)).convert('RGB'), (size, size), Image.LANCZOS)
        shade = Image.new('L', (1, size))
        for yy in range(size):                                   # escurece a parte de baixo para o texto ler bem
            shade.putpixel((0, yy), int(max(0, (yy - size * .35) / (size * .65)) * 215))
        img.paste(Image.new('RGB', (size, size), (8, 12, 24)), (0, 0), shade.resize((size, size)))
        draw = ImageDraw.Draw(img)
        f, lines, px = _fit_title(draw, title, size - 2 * pad, 4, serif=False)
        y = size - pad - 60 - len(lines) * int(px * 1.18)
        draw.rectangle([pad, y - 34, pad + 90, y - 26], fill=base)
        for line in lines:
            draw.text((pad, y), line, fill=(255, 255, 255), font=f)
            y += int(px * 1.18)
        draw.text((pad, size - pad - 24), office, fill=(226, 232, 240), font=_font(28, False))
        _paste_logo(img, logo, (size - pad - 200, pad - 30, 200, 90), 'left')
    elif style == 'citacao':
        img = Image.new('RGB', (size, size), light)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 18, size], fill=base)
        draw.text((pad, pad - 40), '“', fill=base, font=_font(260))
        f, lines, px = _fit_title(draw, title, size - 2 * pad, 6, sizes=(64, 58, 52, 46, 40))
        y = 330
        for line in lines:
            draw.text((pad, y), line, fill=_mix(base, (15, 23, 42), .75), font=f)
            y += int(px * 1.3)
        draw.line([pad, size - pad - 70, pad + 120, size - pad - 70], fill=base, width=4)
        if not _paste_logo(img, logo, (pad, size - pad - 50, 260, 70)):
            draw.text((pad, size - pad - 40), office, fill=_mix(base, (15, 23, 42), .6), font=_font(30, False))
    elif style == 'dica':
        img = Image.new('RGB', (size, size), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, size, 300], fill=base)
        draw.rounded_rectangle([pad, 110, pad + 190, 180], radius=35, fill=(255, 255, 255))
        tag = _font(34, False)
        draw.text((pad + (190 - draw.textlength('DICA', font=tag)) / 2, 124), 'DICA', fill=base, font=tag)
        _paste_logo(img, logo, (size - pad - 220, 100, 220, 100))
        f, lines, px = _fit_title(draw, title, size - 2 * pad, 6, sizes=(68, 60, 54, 48, 42), serif=False)
        y = 380
        for line in lines:
            draw.text((pad, y), line, fill=(15, 23, 42), font=f)
            y += int(px * 1.25)
        draw.rectangle([0, size - 110, size, size], fill=light)
        draw.text((pad, size - 76), office, fill=dark, font=_font(30, False))
    else:                                                        # destaque
        img = Image.new('RGB', (size, size), base)
        grad = Image.linear_gradient('L').rotate(-45, expand=False).resize((size, size))
        img.paste(Image.new('RGB', (size, size), dark), (0, 0), grad)
        draw = ImageDraw.Draw(img)
        draw.rectangle([56, 56, size - 56, size - 56], outline=(255, 255, 255), width=2)
        f, lines, px = _fit_title(draw, title, size - 2 * pad - 40, 6)
        step = int(px * 1.22)
        y = (size - len(lines) * step) // 2 - 30
        for line in lines:
            w = draw.textlength(line, font=f)
            draw.text(((size - w) / 2, y), line, fill=(255, 255, 255), font=f)
            y += step
        if not _paste_logo(img, logo, ((size - 260) // 2, size - 210, 260, 90), 'center'):
            small = _font(32, False)
            w = draw.textlength(office, font=small)
            draw.text(((size - w) / 2, size - 160), office, fill=(255, 255, 255), font=small)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


# ----------------------------------------------------------------------------- armazenamento e link público
def _store(piece, data: bytes) -> str:
    if piece.image_file and default_storage.exists(piece.image_file):
        default_storage.delete(piece.image_file)
    return default_storage.save(f'marketing/img/{uuid.uuid4().hex}.png', ContentFile(data))


def public_url(piece, request=None) -> str:
    token = signing.dumps({'p': piece.pk, 'f': piece.image_file}, salt=SALT, compress=True)
    return absolute(f'/api/v1/publico/marketing/imagem/{token}/', request)


def absolute(path: str, request=None) -> str:
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/')
    if base:
        return f'{base}{path}'
    return request.build_absolute_uri(path) if request is not None else path


def read_token(token: str) -> dict:
    return signing.loads(token, salt=SALT)


def _brand(org):
    if org is None:
        return 'Cadrius', '#1d4ed8', None
    from integrations.email_layout import office_logo, office_style
    logo = office_logo(org)
    return str(org), office_style(org)[1], (logo[0] if logo else None)


def generate(piece, user=None, *, mode: str = 'ia', request=None, style: str = 'destaque', photo=None, refs=None):
    """Gera e anexa a imagem ao conteúdo. Devolve (piece, aviso).

    mode: 'ia' (adicional de mídia; ``refs`` = fotos de referência) | 'marca' (arte pronta; ``style`` e ``photo``) |
    'foto' (``photo`` vira a imagem do post). ``photo``/``refs`` são MarketingAsset do mesmo escritório."""
    from aigov.guard import AIBlocked, run_guarded
    from marketing import media
    notice = ''
    data, source = None, 'marca'
    org = piece.organization
    if mode == 'foto':
        if photo is None:
            raise ImageError('Escolha uma foto.')
        data, source = media.as_post_image(photo), 'foto'
    elif mode == 'ia':
        require_addon(org)
        if not providers(org):
            raise ImageError('A IA de imagem (Gemini) não está disponível agora. Use uma arte pronta ou uma foto.')
        if org is not None:
            from billing.credit_weights import credits_for
            from billing.credits import check_credit_available
            ok, msg = check_credit_available(org, user_id=getattr(user, 'pk', None))
            if credits_for('marketing_image') and not ok:
                raise ImageError(msg)
        ref_bytes = [media.read_bytes(a) for a in (refs or [])[:MAX_REFS]]
        prompt = prompt_for(piece, with_refs=bool(ref_bytes))
        try:
            def fn():
                return _gemini(prompt, ref_bytes)
            data = (run_guarded(organization=org, user=user, kind='marketing', provider='GEMINI', categories=[],
                                input_text=prompt, fn=fn) if org is not None else fn())
            source = 'gemini'
            if org is not None:                                # cobra só a imagem entregue
                from billing.credits import charge
                charge(org, 'marketing_image', user_id=getattr(user, 'pk', None))
        except AIBlocked as exc:
            raise ImageError(f'IA bloqueada pela política do escritório ({exc.message}).') from exc
        except Exception as exc:  # noqa: BLE001 — sem cobrança; a pessoa tenta de novo ou usa uma arte pronta
            logger.warning('Imagem de marketing falhou no Gemini: %s', type(exc).__name__)
            raise ImageError('A IA de imagem não respondeu agora. Tente de novo ou use uma arte pronta.') from exc
    if data is None:
        office, color, logo = _brand(org)
        photo_bytes = media.read_bytes(photo) if photo is not None and style == 'foto' else None
        data = brand_card(piece.title or piece.theme, office, color, style=style, photo=photo_bytes, logo=logo)
    piece.image_file = _store(piece, data)
    piece.image_source = source
    piece.image_url = public_url(piece, request)
    piece.save(update_fields=['image_file', 'image_source', 'image_url', 'updated_at'])
    return piece, notice
