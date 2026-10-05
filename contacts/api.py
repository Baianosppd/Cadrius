"""API do quadro de contatos (CAD-171). Prefixo: /api/v1/contacts/ — escritório do usuário; leitura: todos; escrita: dono/admin/membro;
excluir: dono/admin."""
from __future__ import annotations

import re

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.team_roles import MANAGE_TEAM_ROLES, get_active_membership
from audit import service as audit
from contacts.models import Contact
from contacts.validation import clean_contact
from core.pii import blind_index, filter_by_term

PAGE = 50
WRITE_ROLES = {'OWNER', 'ADMIN', 'MEMBER'}
CONSENT_FIELDS = ('whatsapp_consent', 'email_consent', 'opted_out')


def contact_json(c) -> dict:
    return {'id': c.pk, 'kind': c.kind, 'kind_label': c.get_kind_display(), 'person_type': c.person_type, 'name': c.name,
            'document': c.document, 'email': c.email, 'phone': c.phone, 'tags': c.tags, 'notes': c.notes,
            'whatsapp_consent': c.whatsapp_consent, 'email_consent': c.email_consent, 'opted_out': c.opted_out,
            'consent_updated_at': c.consent_updated_at, 'consent_source': c.consent_source,
            'can_whatsapp': c.can_receive('whatsapp'), 'can_email': c.can_receive('email'),
            'source': c.source, 'created_at': c.created_at, 'updated_at': c.updated_at}


def search(qs, term: str):
    term = (term or '').strip()
    if not term:
        return qs
    if '@' in term:
        return qs.filter(email_bidx=blind_index('contact.email', term, 'text'))
    digits = re.sub(r'\D', '', term)
    if len(digits) >= 10 and len(digits) >= len(term.replace(' ', '')) - 4:   # parece documento/telefone
        return qs.filter(document_bidx=blind_index('contact.document', digits, 'digits')) | \
            qs.filter(phone_bidx=blind_index('contact.phone', digits[-11:] if len(digits) > 11 else digits, 'digits'))
    return filter_by_term(qs, 'name_idx', 'contact.name', term)


def duplicate_email(org, email, exclude_pk=None) -> bool:
    """Mesmo e-mail no escritório = provável contato repetido (a importação também usa o e-mail para juntar)."""
    if not email:
        return False
    qs = Contact.objects.filter(organization=org, email_bidx=blind_index('contact.email', email, 'text'))
    return qs.exclude(pk=exclude_pk).exists() if exclude_pk else qs.exists()


DUPLICATE_EMAIL = 'Já existe um contato com este e-mail. Abra o contato existente para atualizar.'


def _apply_consent(contact, data, user):
    changed = [f for f in CONSENT_FIELDS if f in data and bool(data[f]) != getattr(contact, f)]
    for f in changed:
        setattr(contact, f, bool(data[f]))
    if changed:
        contact.consent_updated_at = timezone.now()
        contact.consent_source = str(data.get('consent_source') or f'registrado por {user.email}')[:120]
    return changed


class _Base(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def membership(self, request, write=False, manage=False):
        m = get_active_membership(request.user)
        if m is None:
            return None, Response({'detail': 'Usuário sem escritório.'}, status=status.HTTP_403_FORBIDDEN)
        if (manage and m.role not in MANAGE_TEAM_ROLES) or (write and m.role not in WRITE_ROLES):
            return None, Response({'detail': 'Seu perfil não permite esta alteração.'}, status=status.HTTP_403_FORBIDDEN)
        return m, None


class ContactListView(_Base):
    def get(self, request):
        m, err = self.membership(request)
        if err:
            return err
        qs = Contact.objects.filter(organization=m.organization)
        kind = request.query_params.get('kind')
        if kind in Contact.Kind.values:
            qs = qs.filter(kind=kind)
        tag = (request.query_params.get('tag') or '').strip()
        rows = list(search(qs, request.query_params.get('q')))
        if tag:
            rows = [c for c in rows if tag in (c.tags or [])]
        rows.sort(key=lambda c: c.name.casefold())                 # nome é cifrado: ordena em Python
        offset = max(int(request.query_params.get('offset') or 0), 0)
        return Response({'total': len(rows), 'resultados': [contact_json(c) for c in rows[offset:offset + PAGE]],
                         'tags': sorted({t for c in Contact.objects.filter(organization=m.organization).only('tags') for t in c.tags})})

    def post(self, request):
        m, err = self.membership(request, write=True)
        if err:
            return err
        values, errors = clean_contact(request.data)
        if errors:
            return Response({'detail': ' '.join(errors), 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        if duplicate_email(m.organization, values['email']):
            return Response({'detail': DUPLICATE_EMAIL}, status=status.HTTP_409_CONFLICT)
        contact = Contact(organization=m.organization, created_by=request.user, **values)
        _apply_consent(contact, request.data, request.user)
        try:
            with transaction.atomic():
                contact.save()
        except IntegrityError:
            return Response({'detail': 'Já existe um contato com este CPF/CNPJ.'}, status=status.HTTP_409_CONFLICT)
        audit.log('contact.created', actor=request.user, organization=m.organization, target=contact,
                  changes={'kind': contact.kind}, data_categories=['identificacao', 'contato'], legal_basis='execucao_contrato')
        from automations.engine import emit
        emit(m.organization, 'contact_created', {'contact_id': contact.pk, 'user_id': str(request.user.pk)}, f'contact-{contact.pk}')
        return Response(contact_json(contact), status=status.HTTP_201_CREATED)


class ContactDetailView(_Base):
    def _get(self, m, pk):
        return Contact.objects.filter(organization=m.organization, pk=pk).first()

    def get(self, request, pk):
        m, err = self.membership(request)
        if err:
            return err
        c = self._get(m, pk)
        return Response(contact_json(c)) if c else Response(status=status.HTTP_404_NOT_FOUND)

    def patch(self, request, pk):
        m, err = self.membership(request, write=True)
        if err:
            return err
        c = self._get(m, pk)
        if c is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        merged = {**contact_json(c), **request.data}
        values, errors = clean_contact(merged)
        if errors:
            return Response({'detail': ' '.join(errors), 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        if duplicate_email(m.organization, values['email'], exclude_pk=c.pk):
            return Response({'detail': DUPLICATE_EMAIL}, status=status.HTTP_409_CONFLICT)
        for k, v in values.items():
            setattr(c, k, v)
        consent = _apply_consent(c, request.data, request.user)
        try:
            with transaction.atomic():
                c.save()
        except IntegrityError:
            return Response({'detail': 'Já existe um contato com este CPF/CNPJ.'}, status=status.HTTP_409_CONFLICT)
        audit.log('contact.updated', actor=request.user, organization=m.organization, target=c,
                  changes={'fields': sorted(set(request.data) - {'consent_source'}), 'consent': consent},
                  data_categories=['identificacao', 'contato'], legal_basis='execucao_contrato')
        return Response(contact_json(c))

    def delete(self, request, pk):
        m, err = self.membership(request, manage=True)
        if err:
            return err
        c = self._get(m, pk)
        if c is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        audit.log('contact.deleted', actor=request.user, organization=m.organization, target=c, changes={'kind': c.kind},
                  data_categories=['identificacao', 'contato'], legal_basis='execucao_contrato')
        c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
