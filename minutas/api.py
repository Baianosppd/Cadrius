"""API de minutas (CAD-173). Prefixo: /api/v1/minutas/

Ler: qualquer pessoa do escritório. Gerar/editar: dono, administrador e advogado. Modelos do escritório: dono e administrador."""
from __future__ import annotations

import re
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from minutas import services
from minutas.builtin import BUILTIN, VARS
from minutas.models import Draft, DraftTemplate

WRITE_ROLES = MANAGE_TEAM_ROLES | {'MEMBER'}
MAX_BODY = 30_000


def draft_json(d, full=True):
    data = {'id': d.pk, 'titulo': d.title, 'modelo': d.template_key, 'fonte': {'tipo': d.source_type, 'id': d.source_id} if d.source_type else None,
            'status': d.status, 'pendencias': d.pending, 'ia': d.ai_provider, 'aviso': d.notice, 'criada_em': d.created_at,
            'atualizada_em': d.updated_at, 'autor': (d.created_by.get_full_name() or d.created_by.email) if d.created_by_id else None,
            'revisada_por': (d.reviewed_by.get_full_name() or d.reviewed_by.email) if d.reviewed_by_id else None}
    if full:
        data.update(conteudo=d.content, citacoes=d.citations)
    return data


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def membership(self, request, roles=None):
        m = get_active_membership(request.user)
        if m is None:
            return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        if roles is not None and m.role not in roles:
            return None, Response({'detail': 'Seu perfil não permite esta ação.'}, status=status.HTTP_403_FORBIDDEN)
        return m, None


class TemplateListView(_Base):
    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        builtin = [{'chave': f'builtin:{k}', 'nome': t['name'], 'tipo': t['kind'], 'corpo': t['body'], 'do_escritorio': False}
                   for k, t in BUILTIN.items()]
        own = [template_json(t) for t in DraftTemplate.objects.filter(organization=m.organization).order_by('-updated_at')]
        return Response({'modelos': own + builtin, 'variaveis': [{'chave': k, 'label': v} for k, v in VARS.items()]})

    def post(self, request):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        name, body = str(request.data.get('nome', '')).strip(), str(request.data.get('corpo', ''))
        if not 3 <= len(name) <= 120 or not 10 <= len(body) <= MAX_BODY:
            return Response({'detail': 'Informe o nome (3 a 120) e o corpo do modelo (10 a 30.000 caracteres).'}, status=status.HTTP_400_BAD_REQUEST)
        t = DraftTemplate.objects.create(organization=m.organization, name=name, body=body, created_by=request.user,
                                         kind=re.sub(r'[^a-z_]', '', str(request.data.get('tipo', 'outro')).lower())[:40] or 'outro')
        audit.log('draft.template_saved', actor=request.user, organization=m.organization, target=t, changes={'nome': name, 'novo': True})
        return Response(template_json(t), status=status.HTTP_201_CREATED)


class TemplateImportView(_Base):
    """POST multipart {arquivo, salvar?} (dono/admin) — CAD-231: importa um modelo do escritório (Word, PDF, texto).
    Sem ``salvar``: devolve a prévia (nome, tipo, corpo com as variáveis e os campos encontrados) para a pessoa conferir."""

    def post(self, request):
        from minutas import importer
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        up = request.FILES.get('arquivo')
        if up is None:
            return Response({'detail': 'Escolha o arquivo do modelo.'}, status=status.HTTP_400_BAD_REQUEST)
        if up.size > importer.MAX_FILE:
            return Response({'detail': 'O arquivo pode ter até 5 MB.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = importer.prepare(up.name, up.read())
        except importer.ImportError_ as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if str(request.data.get('salvar', '')).lower() not in ('1', 'true', 'sim'):
            return Response(data)
        t = DraftTemplate.objects.create(organization=m.organization, name=str(request.data.get('nome') or data['nome'])[:120],
                                         body=data['corpo'], kind=data['tipo'], created_by=request.user)
        audit.log('draft.template_saved', actor=request.user, organization=m.organization, target=t,
                  changes={'nome': t.name, 'novo': True, 'origem': 'importado', 'campos': len(data['campos'])})
        return Response(template_json(t), status=status.HTTP_201_CREATED)


def template_json(t) -> dict:
    fields = sorted(set(services.VAR.findall(t.body)))
    return {'chave': f'org:{t.pk}', 'id': t.pk, 'nome': t.name, 'tipo': t.kind, 'corpo': t.body, 'do_escritorio': True,
            'campos': fields, 'atualizado_em': t.updated_at}


class TemplateDetailView(_Base):
    def patch(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        t = DraftTemplate.objects.filter(organization=m.organization, pk=pk).first()
        if t is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if 'nome' in request.data:
            t.name = str(request.data['nome']).strip()[:120] or t.name
        if 'tipo' in request.data:                        # CAD-231
            t.kind = re.sub(r'[^a-z_]', '', str(request.data['tipo']).lower())[:40] or t.kind
        if 'corpo' in request.data:
            body = str(request.data['corpo'])
            if not 10 <= len(body) <= MAX_BODY:
                return Response({'detail': 'Corpo do modelo entre 10 e 30.000 caracteres.'}, status=status.HTTP_400_BAD_REQUEST)
            t.body = body
        t.save()
        audit.log('draft.template_saved', actor=request.user, organization=m.organization, target=t, changes={'nome': t.name, 'novo': False})
        return Response(template_json(t))

    def delete(self, request, pk):
        m, err = self.membership(request, MANAGE_TEAM_ROLES)
        if err:
            return err
        deleted, _ = DraftTemplate.objects.filter(organization=m.organization, pk=pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


class DraftListView(_Base):
    """GET → últimas 100 (sem o texto). POST {modelo, fonte: documento|publicacao, fonte_id, usar_ia, titulo} → gera a minuta."""

    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        qs = Draft.objects.filter(organization=m.organization).select_related('created_by', 'reviewed_by')
        if request.query_params.get('fonte') in ('documento', 'publicacao') and str(request.query_params.get('fonte_id', '')).isdigit():
            qs = qs.filter(source_type=request.query_params['fonte'], source_id=int(request.query_params['fonte_id']))
        return Response([draft_json(d, full=False) for d in qs[:100]])

    def post(self, request):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        d = request.data
        source_id = d.get('fonte_id')
        try:
            source_id = int(source_id) if source_id not in (None, '') else None
            draft = services.generate(m.organization, request.user, template_key=str(d.get('modelo', '')),
                                      source_type=str(d.get('fonte') or ''), source_id=source_id, use_ai=d.get('usar_ia') is True,
                                      title=str(d.get('titulo') or '').strip())
        except (ValueError, services.DraftError) as exc:
            msg = str(exc) if isinstance(exc, services.DraftError) else 'Fonte inválida.'
            return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
        audit.log('draft.created', actor=request.user, organization=m.organization, target=draft,
                  changes={'modelo': draft.template_key, 'fonte': draft.source_type, 'ia': draft.ai_provider or 'nao'},
                  data_categories=['dados_processuais'])
        return Response(draft_json(draft), status=status.HTTP_201_CREATED)


class DraftDetailView(_Base):
    def _get(self, m, pk):
        return Draft.objects.filter(organization=m.organization, pk=pk).select_related('created_by', 'reviewed_by').first()

    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        d = self._get(m, pk)
        return Response(draft_json(d)) if d else Response(status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, pk):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        d = self._get(m, pk)
        if d is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if 'titulo' in request.data:
            d.title = str(request.data['titulo']).strip()[:200] or d.title
        if 'conteudo' in request.data:
            content = str(request.data['conteudo'])
            if len(content) > 100_000:
                return Response({'detail': 'Texto grande demais.'}, status=status.HTTP_400_BAD_REQUEST)
            d.content, d.pending = content, content.count('[COMPLETAR')
        st = request.data.get('status')
        if st == Draft.Status.REVIEWED:
            if d.pending:
                return Response({'detail': f'Ainda há {d.pending} trecho(s) [COMPLETAR] no texto.'}, status=status.HTTP_400_BAD_REQUEST)
            d.status, d.reviewed_by, d.reviewed_at = Draft.Status.REVIEWED, request.user, timezone.now()
        elif st == Draft.Status.DRAFT:
            d.status, d.reviewed_by, d.reviewed_at = Draft.Status.DRAFT, None, None
        elif 'conteudo' in request.data and d.status == Draft.Status.REVIEWED:
            d.status, d.reviewed_by, d.reviewed_at = Draft.Status.DRAFT, None, None     # mudou o texto: volta a rascunho
        d.save()
        if st == Draft.Status.REVIEWED:
            services.learn(d, request.user)
        audit.log('draft.updated', actor=request.user, organization=m.organization, target=d, changes={'status': d.status})
        return Response(draft_json(d))

    def delete(self, request, pk):
        m, err = self.membership(request, WRITE_ROLES)
        if err:
            return err
        d = self._get(m, pk)
        if d is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('draft.deleted', actor=request.user, organization=m.organization, target=d, changes={'titulo': d.title})
        d.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DraftDocxView(DraftDetailView):
    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        d = self._get(m, pk)
        if d is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('draft.exported', actor=request.user, organization=m.organization, target=d, data_categories=['dados_processuais'])
        name = re.sub(r'\s+', ' ', re.sub(r'[^\w\- ]+', '', d.title)).strip()[:80] or 'minuta'
        resp = HttpResponse(services.to_docx(d.title, d.content),
                            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        ascii_name = name.encode('ascii', 'ignore').decode() or 'minuta'
        resp['Content-Disposition'] = f'attachment; filename="{ascii_name}.docx"; filename*=UTF-8\'\'{quote(name)}.docx'
        return resp
