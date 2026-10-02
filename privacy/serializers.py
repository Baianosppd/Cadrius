from rest_framework import serializers

from privacy.models import ConsentRecord, DataSubjectRequest, LegalDocument, SubprocessorEntry


class LegalDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LegalDocument
        fields = ['id', 'kind', 'version', 'title', 'content_md', 'content_sha256', 'locale', 'requires_reconsent',
                  'needs_legal_review', 'published_at']
        read_only_fields = fields


class SubprocessorSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubprocessorEntry
        fields = ['name', 'country', 'purpose', 'data_categories', 'international_transfer', 'safeguards',
                  'contract_verified']
        read_only_fields = fields


class ConsentRecordSerializer(serializers.ModelSerializer):
    kind = serializers.CharField(source='document.kind', read_only=True)
    version = serializers.CharField(source='document.version', read_only=True)

    class Meta:
        model = ConsentRecord
        fields = ['id', 'kind', 'version', 'purpose', 'granted', 'occurred_at', 'method', 'evidence_sha256']
        read_only_fields = fields


class ConsentCreateSerializer(serializers.Serializer):
    document_id = serializers.PrimaryKeyRelatedField(queryset=LegalDocument.objects.filter(is_current=True))
    granted = serializers.BooleanField(default=True)
    purpose = serializers.CharField(max_length=64, default='essential')


class DataSubjectRequestSerializer(serializers.ModelSerializer):
    overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = DataSubjectRequest
        fields = ['id', 'type', 'status', 'notes', 'opened_at', 'due_at', 'fulfilled_at', 'resolution', 'overdue']
        read_only_fields = ['id', 'status', 'opened_at', 'due_at', 'fulfilled_at', 'resolution', 'overdue']
