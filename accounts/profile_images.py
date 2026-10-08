"""Foto e capa do perfil (CAD-230).

A foto "sumia" ao recarregar a página por dois motivos: o PATCH do perfil ignorava o arquivo (o campo não estava no
serializer) e os arquivos de /media não são servidos em produção. Agora:

- **Envio:** POST /api/v1/auth/profile/imagem/<foto|capa>/ (multipart, campo ``arquivo``). A imagem é validada com o
  Pillow (JPEG, PNG ou WebP; até 5 MB), redimensionada e regravada (sem EXIF, sem localização do celular).
- **Exibição:** o perfil devolve um link assinado ``/api/v1/publico/perfil/<token>/``. O token leva a pessoa, o tipo e o
  nome do arquivo: trocar a imagem muda o link, então o navegador nunca mostra a antiga do cache.
"""
from __future__ import annotations

import io
import secrets

from django.conf import settings
from django.core import signing
from django.core.files.base import ContentFile

SALT = 'cadrius.profile.image'
MAX_BYTES = 5 * 1024 * 1024
KINDS = {
    'foto': {'field': 'profile_picture', 'size': (512, 512), 'crop': True},
    'capa': {'field': 'cover_image', 'size': (1600, 480), 'crop': True},
}
COVER_PRESETS = ('', 'azul', 'verde', 'vinho', 'grafite', 'dourado', 'aurora')


class ImageError(Exception):
    """Mensagem pronta para a tela."""


def _fit(img, size, crop):
    from PIL import Image, ImageOps
    img = ImageOps.exif_transpose(img)                      # respeita a rotação do celular antes de jogar o EXIF fora
    if crop:
        return ImageOps.fit(img, size, Image.LANCZOS, centering=(0.5, 0.5))
    img.thumbnail(size, Image.LANCZOS)
    return img


def save(user, kind: str, upload) -> str:
    """Valida, normaliza e grava a imagem; apaga a anterior. Devolve o nome do arquivo salvo."""
    from PIL import Image, UnidentifiedImageError
    spec = KINDS.get(kind)
    if spec is None:
        raise ImageError('Tipo de imagem inválido.')
    if upload is None:
        raise ImageError('Escolha uma imagem.')
    if upload.size > MAX_BYTES:
        raise ImageError('A imagem pode ter até 5 MB.')
    raw = upload.read()
    try:
        Image.open(io.BytesIO(raw)).verify()                 # arquivo corrompido ou que não é imagem
        img = Image.open(io.BytesIO(raw))
        fmt = (img.format or '').upper()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageError('Não foi possível ler a imagem. Use JPEG, PNG ou WebP.') from exc
    if fmt not in ('JPEG', 'PNG', 'WEBP'):
        raise ImageError('Use uma imagem JPEG, PNG ou WebP.')
    if img.width * img.height > 40_000_000:
        raise ImageError('Imagem grande demais.')
    img = _fit(img, spec['size'], spec['crop'])
    out = io.BytesIO()
    if img.mode in ('RGBA', 'LA', 'P') and kind == 'foto':
        img.convert('RGBA').save(out, 'PNG', optimize=True)
        ext = 'png'
    else:
        img.convert('RGB').save(out, 'JPEG', quality=86, optimize=True, progressive=True)
        ext = 'jpg'
    field = getattr(user, spec['field'])
    old = field.name if field else ''
    field.save(f'{user.pk}-{secrets.token_hex(6)}.{ext}', ContentFile(out.getvalue()), save=False)
    user.save(update_fields=[spec['field']])
    if old and old != field.name:
        field.storage.delete(old)
    return field.name


def remove(user, kind: str) -> None:
    spec = KINDS.get(kind)
    if spec is None:
        raise ImageError('Tipo de imagem inválido.')
    field = getattr(user, spec['field'])
    if field:
        field.delete(save=False)
        user.save(update_fields=[spec['field']])


def url(user, kind: str) -> str | None:
    """Link assinado da imagem (ou None). Absoluto quando há API_PUBLIC_URL (o front e a API ficam em domínios diferentes)."""
    spec = KINDS[kind]
    field = getattr(user, spec['field'], None)
    if not field:
        return None
    token = signing.dumps({'u': str(user.pk), 'k': kind, 'n': field.name}, salt=SALT, compress=True)
    base = (getattr(settings, 'API_PUBLIC_URL', '') or '').rstrip('/')
    return f'{base}/api/v1/publico/perfil/{token}/'


def read_token(token: str) -> dict:
    return signing.loads(token, salt=SALT)
