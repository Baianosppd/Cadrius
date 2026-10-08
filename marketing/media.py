"""Fotos do escritório e vídeo com IA no marketing (CAD-231).

- **Fotos (todos os planos):** o escritório sobe JPEG/PNG/WebP (até 8 MB). O Pillow valida, corrige a rotação, reduz para
  no máximo 2048 px e regrava sem EXIF (nada de localização do celular). Servem de fundo das artes prontas, de imagem do
  post ou de referência para a IA.
- **Vídeo (adicional "Estúdio de mídia com IA"):** Gemini Veo gera um vídeo curto (vertical 9:16, para Reels/Shorts) a
  partir do texto do conteúdo e, se a pessoa escolher, de uma foto do escritório como quadro inicial. A geração no Google
  leva de 1 a 6 minutos: guardamos a operação e a tela consulta o andamento; quando fica pronto, baixamos o MP4 para o
  armazenamento do Cadrius e cobramos o peso "Vídeo curto de marketing" em créditos (só quando entregue).
"""
from __future__ import annotations

import base64
import io
import logging
import uuid
from datetime import timedelta

import requests
from django.core import signing
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from marketing.images import ImageError, _key, absolute, providers, require_addon

logger = logging.getLogger(__name__)

SALT = 'cadrius.marketing.file'
MAX_UPLOAD = 8 * 1024 * 1024
MAX_SIDE = 2048
MAX_ASSETS = 200
VIDEO_MODEL_ENV = 'MARKETING_VIDEO_GEMINI_MODEL'
API = 'https://generativelanguage.googleapis.com/v1beta'
VIDEO_TIMEOUT = timedelta(minutes=20)
MAX_VIDEO = 100 * 1024 * 1024
VIDEO_STYLE = ('Vídeo curto vertical, profissional e sóbrio, para rede social de escritório de advocacia brasileiro. Sem texto na '
               'tela, sem logotipos de terceiros, sem pessoas famosas, sem promessa de resultado, sem símbolos de dinheiro.')


# ----------------------------------------------------------------------------- fotos do escritório
def save_asset(org, user, upload, scope='escritorio'):
    from PIL import Image, ImageOps, UnidentifiedImageError
    from marketing.models import MarketingAsset
    if upload is None:
        raise ImageError('Escolha uma imagem.')
    if upload.size > MAX_UPLOAD:
        raise ImageError('A imagem pode ter até 8 MB.')
    qs = MarketingAsset.objects.filter(scope=scope, organization=org)
    if qs.count() >= MAX_ASSETS:
        raise ImageError(f'Limite de {MAX_ASSETS} imagens: apague as que não usa mais.')
    raw = upload.read()
    try:
        Image.open(io.BytesIO(raw)).verify()
        img = Image.open(io.BytesIO(raw))
        fmt = (img.format or '').upper()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageError('Não foi possível ler a imagem. Use JPEG, PNG ou WebP.') from exc
    if fmt not in ('JPEG', 'PNG', 'WEBP'):
        raise ImageError('Use uma imagem JPEG, PNG ou WebP.')
    if img.width * img.height > 40_000_000:
        raise ImageError('Imagem grande demais.')
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    if img.mode in ('RGBA', 'LA', 'P'):                       # mantém transparência (logos, selos)
        img.convert('RGBA').save(out, 'PNG', optimize=True)
        ext = 'png'
    else:
        img.convert('RGB').save(out, 'JPEG', quality=88, optimize=True, progressive=True)
        ext = 'jpg'
    name = default_storage.save(f'marketing/fotos/{uuid.uuid4().hex}.{ext}', ContentFile(out.getvalue()))
    label = (getattr(upload, 'name', '') or 'Imagem').rsplit('/', 1)[-1].rsplit('.', 1)[0][:120]
    return MarketingAsset.objects.create(scope=scope, organization=org, name=label, file=name, width=img.width,
                                         height=img.height, created_by=user)


def delete_asset(asset):
    if asset.file and default_storage.exists(asset.file):
        default_storage.delete(asset.file)
    asset.delete()


def read_bytes(asset) -> bytes:
    if asset is None or not asset.file or not default_storage.exists(asset.file):
        raise ImageError('A imagem escolhida não existe mais.')
    with default_storage.open(asset.file, 'rb') as fh:
        return fh.read()


def as_post_image(asset) -> bytes:
    """A foto vira a imagem do post (PNG, até 1440 px no lado maior; o Instagram aceita de 4:5 a 1,91:1)."""
    from PIL import Image, ImageOps
    img = Image.open(io.BytesIO(read_bytes(asset))).convert('RGB')
    ratio = img.width / img.height
    if ratio < 0.8:                                            # mais alta que 4:5: corta no centro
        img = ImageOps.fit(img, (img.width, int(img.width / 0.8)), Image.LANCZOS)
    elif ratio > 1.91:
        img = ImageOps.fit(img, (int(img.height * 1.91), img.height), Image.LANCZOS)
    img.thumbnail((1440, 1440), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, 'PNG', optimize=True)
    return out.getvalue()


def file_url(path: str, request=None) -> str:
    """Link assinado para um arquivo do marketing (foto do escritório ou vídeo)."""
    if not path:
        return ''
    token = signing.dumps({'f': path}, salt=SALT, compress=True)
    return absolute(f'/api/v1/publico/marketing/arquivo/{token}/', request)


def read_file_token(token: str) -> str:
    path = str(signing.loads(token, salt=SALT).get('f') or '')
    if not path.startswith(('marketing/fotos/', 'marketing/video/')) or '..' in path:
        raise signing.BadSignature('caminho inválido')
    return path


def asset_json(a, request=None):
    return {'id': a.pk, 'nome': a.name, 'url': file_url(a.file, request), 'largura': a.width, 'altura': a.height,
            'criada_em': a.created_at}


# ----------------------------------------------------------------------------- vídeo (Gemini Veo)
def video_prompt(piece, hint: str = '') -> str:
    scene = (hint or piece.image_hint or '').strip() or f'Cena que represente o tema "{piece.theme}"'
    return f'{VIDEO_STYLE}\nCena: {scene[:500]}\nTema: {piece.theme[:150]}'


def start_video(piece, user=None, *, hint: str = '', photo=None):
    """Pede o vídeo ao Gemini Veo e guarda a operação. Não cobra ainda (cobra quando o vídeo chega)."""
    from aigov.guard import AIBlocked, run_guarded
    org = piece.organization
    require_addon(org)
    if not providers(org):
        raise ImageError('A IA de vídeo (Gemini) não está disponível agora.')
    if piece.video_status == 'gerando':
        raise ImageError('Já tem um vídeo sendo gerado para este conteúdo.')
    if org is not None:
        from billing.credit_weights import credits_for
        from billing.credits import check_credit_available
        ok, msg = check_credit_available(org, user_id=getattr(user, 'pk', None))
        if credits_for('marketing_video') and not ok:
            raise ImageError(msg)
    prompt = video_prompt(piece, hint)
    instance = {'prompt': prompt}
    if photo is not None:                                      # foto do escritório como quadro inicial
        raw = read_bytes(photo)
        instance['image'] = {'bytesBase64Encoded': base64.b64encode(raw).decode(),
                             'mimeType': 'image/png' if raw.startswith(b'\x89PNG') else 'image/jpeg'}
    model = _key(VIDEO_MODEL_ENV) or 'veo-3.1-fast-generate-preview'

    def call():
        resp = requests.post(f'{API}/models/{model}:predictLongRunning', timeout=60,
                             headers={'x-goog-api-key': _key('GEMINI_API_KEY')},
                             json={'instances': [instance], 'parameters': {'aspectRatio': '9:16'}})
        if resp.status_code >= 400:
            raise ImageError(f'Gemini recusou o vídeo ({resp.status_code}).')
        name = resp.json().get('name') or ''
        if not name.startswith('models/'):
            raise ImageError('Gemini não aceitou o pedido de vídeo.')
        return name
    try:
        op = (run_guarded(organization=org, user=user, kind='marketing', provider='GEMINI', categories=[], input_text=prompt,
                          fn=call) if org is not None else call())
    except AIBlocked as exc:
        raise ImageError(f'IA bloqueada pela política do escritório ({exc.message}).') from exc
    except ImageError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning('Vídeo de marketing: falha ao pedir ao Gemini: %s', type(exc).__name__)
        raise ImageError('A IA de vídeo não respondeu agora. Tente de novo em instantes.') from exc
    piece.video_op, piece.video_status, piece.video_error = op[:300], 'gerando', ''
    piece.video_started_at = timezone.now()
    piece.save(update_fields=['video_op', 'video_status', 'video_error', 'video_started_at', 'updated_at'])
    return piece


def _fail(piece, msg):
    piece.video_status, piece.video_error, piece.video_op = 'falhou', msg[:300], ''
    piece.save(update_fields=['video_status', 'video_error', 'video_op', 'updated_at'])
    return piece


def poll_video(piece, user=None):
    """Consulta a operação no Google; quando pronta, baixa o MP4 e cobra. Idempotente (chamada pela tela)."""
    if piece.video_status != 'gerando' or not piece.video_op:
        return piece
    if piece.video_started_at and timezone.now() - piece.video_started_at > VIDEO_TIMEOUT:
        return _fail(piece, 'O Google demorou demais para entregar o vídeo. Tente de novo.')
    headers = {'x-goog-api-key': _key('GEMINI_API_KEY')}
    try:
        resp = requests.get(f'{API}/{piece.video_op}', headers=headers, timeout=30)
        body = resp.json() if resp.status_code < 500 else {}
    except Exception as exc:  # noqa: BLE001 — rede: tenta na próxima consulta
        logger.info('Vídeo de marketing: consulta falhou: %s', type(exc).__name__)
        return piece
    if resp.status_code >= 400 and resp.status_code < 500:
        return _fail(piece, f'O Google recusou a consulta do vídeo ({resp.status_code}).')
    if not body.get('done'):
        return piece
    if body.get('error'):
        return _fail(piece, 'O Google não gerou o vídeo (o pedido pode ter esbarrado nas regras de conteúdo).')
    samples = (((body.get('response') or {}).get('generateVideoResponse') or {}).get('generatedSamples') or [])
    uri = ((samples[0] if samples else {}).get('video') or {}).get('uri')
    if not uri or not uri.startswith('https://'):
        return _fail(piece, 'O Google não devolveu o vídeo (o pedido pode ter esbarrado nas regras de conteúdo).')
    try:
        dl = requests.get(uri, headers=headers, timeout=120, stream=True)
        dl.raise_for_status()
        buf = io.BytesIO()
        for chunk in dl.iter_content(1024 * 256):
            buf.write(chunk)
            if buf.tell() > MAX_VIDEO:
                return _fail(piece, 'Vídeo grande demais.')
    except Exception as exc:  # noqa: BLE001 — tenta baixar de novo na próxima consulta
        logger.info('Vídeo de marketing: download falhou: %s', type(exc).__name__)
        return piece
    from marketing.models import ContentPiece
    old_file, op = piece.video_file, piece.video_op
    name = default_storage.save(f'marketing/video/{uuid.uuid4().hex}.mp4', ContentFile(buf.getvalue()))
    # duas consultas ao mesmo tempo: só a primeira grava e cobra
    won = ContentPiece.objects.filter(pk=piece.pk, video_status='gerando', video_op=op).update(
        video_file=name, video_status='pronto', video_op='', video_error='', updated_at=timezone.now())
    if not won:
        default_storage.delete(name)
        piece.refresh_from_db()
        return piece
    if old_file and default_storage.exists(old_file):
        default_storage.delete(old_file)
    piece.refresh_from_db()
    if piece.organization_id:
        from billing.credits import charge
        charge(piece.organization, 'marketing_video', user_id=getattr(user, 'pk', None))
    return piece
