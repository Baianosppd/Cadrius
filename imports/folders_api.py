"""API da importação da carteira por pastas (CAD-234). Prefixo: /api/v1/imports/pastas/.

listar (Drive ou .zip) → prévia (nada gravado) → importar (segundo plano) → acompanhar o progresso."""
from __future__ import annotations

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from audit import service as audit
from imports import folders
from imports.api import _membership
from imports.models import FolderImport


def max_zip_bytes() -> int:
    return int(getattr(settings, 'FOLDER_IMPORT_MAX_ZIP_BYTES', 2 * 1024 ** 3))


def job_json(job: FolderImport) -> dict:
    data = {'id': job.pk, 'origem': job.source, 'origem_label': job.get_source_display(), 'nome': job.label, 'status': job.status,
            'status_label': job.get_status_display(), 'progresso': job.progress, 'opcoes': {k: v for k, v in job.options.items()
                                                                                             if k != 'usuario'},
            'criado_em': job.created_at, 'concluido_em': job.finished_at}
    if job.status == FolderImport.Status.LISTED:
        data['previa'] = folders.preview(job)
    return data


def _drive_state(user) -> dict:
    from gcal import platform
    from gcal.models import GoogleCalendarLink
    link = GoogleCalendarLink.objects.filter(user=user, status=GoogleCalendarLink.Status.ACTIVE).first()
    return {'habilitado': platform.drive_import_enabled(), 'google_conectado': link is not None,
            'leitura_autorizada': bool(link and link.has_scope(platform.DRIVE_READONLY))}


class FolderImportListView(APIView):
    """GET — situação do Google + importações recentes. POST {link} — lista a pasta do Drive e cria a prévia."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        m, err = _membership(request)
        if err:
            return err
        jobs = FolderImport.objects.filter(organization=m.organization)[:10]
        return Response({'drive': _drive_state(request.user), 'limite_zip_mb': max_zip_bytes() // (1024 * 1024),
                         'importacoes': [{**job_json(j), 'previa': None} for j in jobs]})

    def post(self, request):
        m, err = _membership(request, write=True)
        if err:
            return err
        link = folders.drive_link(request.user)
        if link is None:
            return Response({'detail': 'Autorize a leitura do Google Drive para importar as pastas.', 'code': 'drive_auth'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            fid = folders.drive_folder_id(request.data.get('link', ''))
            label, plan, loose = folders.plan_from_drive(link, fid)
        except folders.FolderImportError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        job = FolderImport.objects.create(organization=m.organization, created_by=request.user, source=FolderImport.Source.DRIVE,
                                          label=label, drive_folder_id=fid, plan=plan,
                                          progress={'soltos': len(loose)})
        return Response(job_json(job), status=status.HTTP_201_CREATED)


class FolderImportZipView(APIView):
    """POST multipart ``arquivo`` (.zip) — lê o índice e cria a prévia."""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        m, err = _membership(request, write=True)
        if err:
            return err
        f = request.FILES.get('arquivo')
        if f is None or not f.name.lower().endswith('.zip'):
            return Response({'detail': 'Envie o .zip da pasta (no Drive: botão direito na pasta → Fazer download).'},
                            status=status.HTTP_400_BAD_REQUEST)
        if f.size > max_zip_bytes():
            return Response({'detail': f'O .zip passa de {max_zip_bytes() // (1024 * 1024)} MB. Importe por partes.'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            plan, loose = folders.plan_from_zip(f)
        except folders.FolderImportError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if not plan:
            return Response({'detail': 'Não achei pastas de clientes no .zip: cada cliente deve ser uma pasta com os arquivos dentro.'},
                            status=status.HTTP_400_BAD_REQUEST)
        f.seek(0)
        path = folders.keep_archive(f)
        job = FolderImport.objects.create(organization=m.organization, created_by=request.user, source=FolderImport.Source.ZIP,
                                          label=f.name[:255], archive_path=path, plan=plan, progress={'soltos': len(loose)})
        return Response(job_json(job), status=status.HTTP_201_CREATED)


class FolderImportDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser]

    def _job(self, request, write=False):
        m, err = _membership(request, write=write)
        if err:
            return None, err
        job = FolderImport.objects.filter(organization=m.organization, pk=self.kwargs['pk']).first()
        if job is None:
            return None, Response({'detail': 'Importação não encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        return job, None

    def get(self, request, pk):
        job, err = self._job(request)
        return err or Response(job_json(job))

    def delete(self, request, pk):
        job, err = self._job(request, write=True)
        if err:
            return err
        if job.status == FolderImport.Status.RUNNING:
            return Response({'detail': 'A importação já está em andamento.'}, status=status.HTTP_409_CONFLICT)
        if job.status == FolderImport.Status.LISTED:
            folders.discard_archive(job)
            job.status, job.plan = FolderImport.Status.CANCELED, []
            job.save(update_fields=['status', 'plan', 'archive_path'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class FolderImportRunView(FolderImportDetailView):
    """POST {selecionadas: [índices], ler_com_ia: bool} — importa em segundo plano."""

    def post(self, request, pk):
        job, err = self._job(request, write=True)
        if err:
            return err
        if job.status != FolderImport.Status.LISTED:
            return Response({'detail': 'Esta prévia já foi usada. Liste a pasta de novo.'}, status=status.HTTP_409_CONFLICT)
        try:
            folders.start(job, request.user, request.data.get('selecionadas'), request.data.get('ler_com_ia') is True)
        except folders.FolderImportError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        audit.log('data.import', actor=request.user, organization=job.organization,
                  changes={'tipo': 'pastas', 'etapa': 'iniciada', 'origem': job.source, 'pastas': len(job.options['selecionadas'])})
        return Response(job_json(job), status=status.HTTP_202_ACCEPTED)
