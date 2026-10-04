"""Armazenamento de arquivos cifrado em repouso (CAD-164): o conteúdo dos documentos dos clientes nunca fica legível no disco/backup.

Formato do arquivo: ``CADENC1\\n`` + token Fernet (mesma ``ENCRYPTION_KEY`` e rotação de ``core.utils``). Arquivo antigo, sem esse cabeçalho,
continua legível (legado em texto puro) até rodar ``manage.py encrypt_files``. Fernet cifra a mensagem inteira: por isso há um **teto de
tamanho** (``DOCUMENT_MAX_BYTES``, 25 MB) — arquivos maiores são recusados no upload, em vez de estourar a memória do servidor.
"""
from __future__ import annotations

import io
import os

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

from core.utils import _build_fernet

MAGIC = b'CADENC1\n'


def encrypt_bytes(data: bytes) -> bytes:
    return MAGIC + _build_fernet().encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    if not data.startswith(MAGIC):
        return data   # legado em texto puro
    return _build_fernet().decrypt(data[len(MAGIC):])


@deconstructible
class EncryptedFileSystemStorage(FileSystemStorage):
    def _save(self, name, content):
        content.seek(0)
        encrypted = ContentFile(encrypt_bytes(content.read()))
        return super()._save(name, encrypted)

    def _open(self, name, mode='rb'):
        with super()._open(name, 'rb') as fh:
            raw = fh.read()
        return ContentFile(decrypt_bytes(raw), name=os.path.basename(name))

    def is_encrypted(self, name) -> bool:
        with super()._open(name, 'rb') as fh:
            return fh.read(len(MAGIC)) == MAGIC

    def rewrite_encrypted(self, name) -> bool:
        """Cifra no mesmo caminho um arquivo legado. Devolve False se já estava cifrado."""
        path = self.path(name)
        with open(path, 'rb') as fh:
            raw = fh.read()
        if raw.startswith(MAGIC):
            return False
        tmp = f'{path}.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(encrypt_bytes(raw))
        os.replace(tmp, path)
        return True


def encrypted_storage():
    """Chamável referenciado nas migrações (evita instância fixa com caminho absoluto)."""
    return EncryptedFileSystemStorage()


def read_all(file_field) -> bytes:
    with file_field.open('rb') as fh:
        return fh.read() if not isinstance(fh, io.BytesIO) else fh.getvalue()
