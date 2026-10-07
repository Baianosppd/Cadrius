"""Imagem de verdade para o conteúdo de marketing (CAD-226).

Antes o Cadrius só sugeria a arte ("Arte sóbria com o título…") e o post saía sem imagem. Agora:
1. **IA de imagem** (OpenAI ``gpt-image-1`` ou Gemini ``gemini-2.5-flash-image``, a que estiver configurada e permitida): gera
   uma imagem a partir da sugestão de arte e do tema, com as regras da OAB (sobriedade, nada de promessa, nenhum dado de
   cliente). Cobra o peso "Imagem de marketing" em créditos.
2. **Arte da marca** (sem IA, sem custo): cartão 1080×1080 na cor do escritório com o título — para quando não há IA de imagem.

A imagem fica no armazenamento do Cadrius e ganha um link público assinado (o Instagram exige URL pública para publicar).
"""
from __future__ import annotations

import base64
import io
import logging
import os
import textwrap
import uuid

import requests
from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

SALT = 'cadrius.marketing.image'
TIMEOUT = 120
OPENAI_MODEL_ENV, GEMINI_MODEL_ENV = 'MARKETING_IMAGE_OPENAI_MODEL', 'MARKETING_IMAGE_GEMINI_MODEL'
STYLE = ('Fotografia ou ilustração editorial profissional para rede social de escritório de advocacia brasileiro, sóbria e '
         'elegante, luz natural, sem logotipos de terceiros, sem pessoas famosas, sem símbolos de dinheiro ou ostentação, '
         'sem texto escrito na imagem. Formato quadrado.')


class ImageError(Exception):
    """Mensagem pronta para a tela."""


def _key(env: str) -> str:
    return (os.environ.get(env) or getattr(settings, env, '') or '').strip()


def providers(org=None) -> list[str]:
    """IAs de imagem configuradas e permitidas pelo escritório, na ordem de preferência."""
    from aigov.guard import get_policy, global_ai_enabled
    if not global_ai_enabled():
        return []
    allowed = set(get_policy(org).allowed_providers or []) if org is not None else set()
    out = [p for p, env in (('OPENAI', 'OPENAI_API_KEY'), ('GEMINI', 'GEMINI_API_KEY')) if _key(env)]
    return [p for p in out if not allowed or p in allowed]


def prompt_for(piece) -> str:
    hint = (piece.image_hint or '').strip() or f'Imagem que represente o tema "{piece.theme}"'
    return f'{STYLE}\nCena: {hint[:400]}\nTema do post: {piece.theme[:150]}'


def _openai(prompt: str) -> bytes:
    resp = requests.post('https://api.openai.com/v1/images/generations', timeout=TIMEOUT,
                         headers={'Authorization': f'Bearer {_key("OPENAI_API_KEY")}'},
                         json={'model': _key(OPENAI_MODEL_ENV) or 'gpt-image-1', 'prompt': prompt, 'size': '1024x1024', 'n': 1})
    if resp.status_code >= 400:
        raise ImageError(f'OpenAI recusou a imagem ({resp.status_code}).')
    item = (resp.json().get('data') or [{}])[0]
    if item.get('b64_json'):
        return base64.b64decode(item['b64_json'])
    if item.get('url'):
        return requests.get(item['url'], timeout=TIMEOUT).content
    raise ImageError('OpenAI não devolveu imagem.')


def _gemini(prompt: str) -> bytes:
    model = _key(GEMINI_MODEL_ENV) or 'gemini-2.5-flash-image'
    resp = requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', timeout=TIMEOUT,
                         headers={'x-goog-api-key': _key('GEMINI_API_KEY')},
                         json={'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'responseModalities': ['IMAGE']}})
    if resp.status_code >= 400:
        raise ImageError(f'Gemini recusou a imagem ({resp.status_code}).')
    for cand in resp.json().get('candidates') or []:
        for part in (cand.get('content') or {}).get('parts') or []:
            data = (part.get('inlineData') or part.get('inline_data') or {}).get('data')
            if data:
                return base64.b64decode(data)
    raise ImageError('Gemini não devolveu imagem.')


def brand_card(title: str, office: str, color: str = '#1d4ed8') -> bytes:
    """Arte da marca, sem IA: fundo na cor do escritório, título grande e nome do escritório."""
    from PIL import Image, ImageDraw, ImageFont
    size = 1080
    img = Image.new('RGB', (size, size), color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([60, 60, size - 60, size - 60], outline=(255, 255, 255), width=3)

    def font(px):
        for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
            if os.path.exists(path):
                return ImageFont.truetype(path, px)
        return ImageFont.load_default(size=px)
    big, small = font(64), font(34)
    lines = textwrap.wrap(title.strip() or 'Conteúdo jurídico', width=22)[:6]
    y = (size - len(lines) * 84) // 2 - 40
    for line in lines:
        w = draw.textlength(line, font=big)
        draw.text(((size - w) / 2, y), line, fill=(255, 255, 255), font=big)
        y += 84
    w = draw.textlength(office[:40], font=small)
    draw.text(((size - w) / 2, size - 150), office[:40], fill=(255, 255, 255), font=small)
    buf = io.BytesIO()
    img.save(buf, 'PNG', optimize=True)
    return buf.getvalue()


def _store(piece, data: bytes) -> str:
    if piece.image_file and default_storage.exists(piece.image_file):
        default_storage.delete(piece.image_file)
    return default_storage.save(f'marketing/img/{uuid.uuid4().hex}.png', ContentFile(data))


def public_url(piece, request=None) -> str:
    token = signing.dumps({'p': piece.pk, 'f': piece.image_file}, salt=SALT, compress=True)
    path = f'/api/v1/publico/marketing/imagem/{token}/'
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/')
    if base:
        return f'{base}{path}'
    return request.build_absolute_uri(path) if request is not None else path


def read_token(token: str) -> dict:
    return signing.loads(token, salt=SALT)


def generate(piece, user=None, *, mode: str = 'ia', request=None):
    """Gera e anexa a imagem ao conteúdo. mode = 'ia' | 'marca'. Devolve (piece, aviso)."""
    from aigov.guard import AIBlocked, run_guarded
    notice = ''
    data, source = None, 'marca'
    org = piece.organization
    if mode == 'ia':
        chain = providers(org)
        if not chain:
            notice = 'Nenhuma IA de imagem configurada (OpenAI ou Gemini): fizemos a arte da marca.'
        else:
            if org is not None:
                from billing.credit_weights import credits_for
                from billing.credits import check_credit_available
                ok, msg = check_credit_available(org, user_id=getattr(user, 'pk', None))
                if credits_for('marketing_image') and not ok:
                    raise ImageError(msg)
            prompt = prompt_for(piece)
            for provider in chain:
                try:
                    fn = (lambda p=prompt: _openai(p)) if provider == 'OPENAI' else (lambda p=prompt: _gemini(p))
                    data = (run_guarded(organization=org, user=user, kind='marketing', provider=provider, categories=[],
                                        input_text=prompt, fn=fn) if org is not None else fn())
                    source = provider.lower()
                    if org is not None:                    # cobra só a imagem entregue
                        from billing.credits import charge
                        charge(org, 'marketing_image', user_id=getattr(user, 'pk', None))
                    break
                except AIBlocked as exc:
                    notice = f'IA bloqueada pela política do escritório ({exc.message}).'
                except Exception as exc:  # noqa: BLE001 — tenta a próxima IA; no fim, a arte da marca
                    logger.warning('Imagem de marketing falhou em %s: %s', provider, type(exc).__name__)
                    notice = 'A IA de imagem não respondeu agora: fizemos a arte da marca. Tente de novo mais tarde.'
    if data is None:
        from integrations.email_layout import office_style
        color = office_style(org)[1] if org is not None else '#1d4ed8'
        data = brand_card(piece.title or piece.theme, str(org) if org is not None else 'Cadrius', color)
    piece.image_file = _store(piece, data)
    piece.image_source = source
    piece.image_url = public_url(piece, request)
    piece.save(update_fields=['image_file', 'image_source', 'image_url', 'updated_at'])
    return piece, notice
