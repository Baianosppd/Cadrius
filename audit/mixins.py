"""Mixin para ViewSets DRF: audita create/update/destroy e leituras de detalhe sensíveis."""
from __future__ import annotations

from audit import service


class AuditedModelMixin:
    """
    ``audit_prefix``      — prefixo da ação (ex.: 'workflow' -> workflow.created/updated/deleted).
    ``audit_read_action`` — se definido (ex.: 'data.read'), audita ``retrieve``.
    ``audit_categories``  — categorias de dados envolvidas (liga à ROPA/LGPD).
    """

    audit_prefix: str = ''
    audit_read_action: str = ''
    audit_categories: tuple = ()

    def _audit(self, verb: str, instance, changes=None):
        service.log(
            f'{self.audit_prefix}.{verb}', target=instance, changes=changes,
            data_categories=self.audit_categories, legal_basis='contrato',
        )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self._audit('created', serializer.instance, {'fields': sorted(serializer.validated_data)})

    def perform_update(self, serializer):
        super().perform_update(serializer)
        self._audit('updated', serializer.instance, {'fields': sorted(serializer.validated_data)})

    def perform_destroy(self, instance):
        target_type, target_id = instance.__class__.__name__, str(instance.pk)
        super().perform_destroy(instance)
        service.log(
            f'{self.audit_prefix}.deleted', target_type=target_type, target_id=target_id,
            data_categories=self.audit_categories, legal_basis='contrato',
        )

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        if self.audit_read_action:
            service.log(
                self.audit_read_action, target=self.get_object(),
                data_categories=self.audit_categories, legal_basis='contrato',
            )
        return response

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if self.audit_read_action:
            # Uma entrada por listagem (volume), com a contagem — não uma por registo.
            data = response.data
            count = data.get('count') if isinstance(data, dict) else len(data)
            service.log(
                'data.bulk_read', target_type=self.queryset.model.__name__,
                changes={'count': count}, data_categories=self.audit_categories, legal_basis='contrato',
            )
        return response
