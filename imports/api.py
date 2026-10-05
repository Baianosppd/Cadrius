"""API de importação (CAD-171). Prefixo: /api/v1/imports/ — enviar → mapear → simular → importar. Nada é gravado antes de "importar"."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import get_active_membership
from audit import service as audit
from imports import targets
from imports.models import ImportJob
from imports.readers import ReadError, read_file

WRITE_ROLES = {'OWNER', 'ADMIN', 'MEMBER'}
PREVIEW_ROWS = 50
MAX_ERRORS_KEPT = 200


def job_json(job, with_sample=False) -> dict:
    data = {'id': job.pk, 'target': job.target, 'target_label': job.get_target_display(), 'filename': job.filename,
            'status': job.status, 'status_label': job.get_status_display(), 'columns': job.columns, 'rows_total': job.rows_total,
            'mapping': job.mapping, 'summary': job.summary, 'errors': job.errors[:MAX_ERRORS_KEPT], 'created_at': job.created_at,
            'finished_at': job.finished_at, 'fields': targets.field_list(job.target)}
    if with_sample:
        data['sample'] = job.rows[:5]
    return data


def _membership(request, write=False):
    m = get_active_membership(request.user)
    if m is None:
        return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
    if write and m.role not in WRITE_ROLES:
        return None, Response({'detail': 'Seu perfil não permite importar dados.'}, status=status.HTTP_403_FORBIDDEN)
    return m, None


def _plan(job, org):
    """Valida todas as linhas sem gravar: [(nº da linha, valores, erros, existente, bruto)]."""
    plan_fn, _ = targets.PLANNERS[job.target]
    seen, out = set(), []
    for i, row in enumerate(job.rows, start=2):                     # linha 1 = cabeçalho
        raw = targets.row_values(job.mapping, row)
        values, errors, existing = plan_fn(org, raw, seen)
        out.append((i, values, errors, existing, raw))
    return out


class ImportListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        m, err = _membership(request)
        if err:
            return err
        return Response([job_json(j) for j in ImportJob.objects.filter(organization=m.organization)[:30]])

    def post(self, request):
        """multipart: file + target (contacts|cases)."""
        m, err = _membership(request, write=True)
        if err:
            return err
        target = request.data.get('target')
        upload = request.FILES.get('file')
        if target not in ImportJob.Target.values or upload is None:
            return Response({'detail': 'Envie o arquivo e escolha o destino.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            columns, rows = read_file(upload.name, upload.read(2_000_001))
        except ReadError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        job = ImportJob.objects.create(organization=m.organization, created_by=request.user, target=target,
                                       filename=upload.name[:200], columns=columns, rows=rows, rows_total=len(rows),
                                       mapping=targets.suggest_mapping(target, columns))
        return Response(job_json(job, with_sample=True), status=status.HTTP_201_CREATED)


class ImportDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get(self, request, pk, write=False):
        m, err = _membership(request, write=write)
        if err:
            return None, None, err
        job = ImportJob.objects.filter(organization=m.organization, pk=pk).first()
        return m, job, (Response(status=status.HTTP_404_NOT_FOUND) if job is None else None)

    def get(self, request, pk):
        _, job, err = self._get(request, pk)
        return err or Response(job_json(job, with_sample=job.status in (ImportJob.Status.UPLOADED, ImportJob.Status.PREVIEWED)))

    def delete(self, request, pk):
        _, job, err = self._get(request, pk, write=True)
        if err:
            return err
        if job.status != ImportJob.Status.DONE:
            job.status, job.rows, job.finished_at = ImportJob.Status.CANCELED, [], timezone.now()
            job.save(update_fields=['status', 'rows', 'finished_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ImportPreviewView(ImportDetailView):
    """POST {mapping}: simula todas as linhas (nada é gravado) e devolve o que seria criado/atualizado e os erros."""

    def post(self, request, pk):
        m, job, err = self._get(request, pk, write=True)
        if err:
            return err
        if job.status not in (ImportJob.Status.UPLOADED, ImportJob.Status.PREVIEWED):
            return Response({'detail': 'Esta importação já foi concluída ou cancelada.'}, status=status.HTTP_409_CONFLICT)
        mapping = {str(k): v for k, v in (request.data.get('mapping') or {}).items() if v}
        problems = targets.validate_mapping(job.target, mapping)
        if problems:
            return Response({'detail': ' '.join(problems)}, status=status.HTTP_400_BAD_REQUEST)
        job.mapping = mapping
        plan = _plan(job, m.organization)
        counts = {'create': 0, 'update': 0, 'errors': 0}
        preview, errors = [], []
        for line, values, errs, existing, _ in plan:
            action = 'erro' if errs else ('atualizar' if existing else 'criar')
            counts['errors' if errs else ('update' if existing else 'create')] += 1
            if errs:
                errors.append({'row': line, 'errors': errs})
            if len(preview) < PREVIEW_ROWS:
                preview.append({'row': line, 'action': action, 'errors': errs, 'values': values or {}})
        job.status, job.summary, job.errors = ImportJob.Status.PREVIEWED, {'preview': counts}, errors[:MAX_ERRORS_KEPT]
        job.save(update_fields=['mapping', 'status', 'summary', 'errors'])
        return Response({**job_json(job), 'counts': counts, 'preview': preview})


class ImportCommitView(ImportDetailView):
    """POST: importa as linhas válidas (as com erro ficam de fora e aparecem no relatório). Exige ter simulado antes."""

    def post(self, request, pk):
        m, job, err = self._get(request, pk, write=True)
        if err:
            return err
        if job.status != ImportJob.Status.PREVIEWED:
            return Response({'detail': 'Simule a importação antes de importar.'}, status=status.HTTP_409_CONFLICT)
        _, apply_fn = targets.PLANNERS[job.target]
        result = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}
        errors = []
        with transaction.atomic():
            for line, values, errs, existing, raw in _plan(job, m.organization):
                if errs:
                    result['errors'] += 1
                    errors.append({'row': line, 'errors': errs})
                    continue
                result[apply_fn(m.organization, request.user, raw, values, existing, job.filename)] += 1
            job.status, job.summary, job.errors = ImportJob.Status.DONE, result, errors[:MAX_ERRORS_KEPT]
            job.rows, job.finished_at = [], timezone.now()                 # o conteúdo lido não fica guardado
            job.save(update_fields=['status', 'summary', 'errors', 'rows', 'finished_at'])
        audit.log('data.import', actor=request.user, organization=m.organization, target=job,
                  changes={'target': job.target, **result}, data_categories=['identificacao', 'contato'], legal_basis='execucao_contrato')
        return Response(job_json(job))
