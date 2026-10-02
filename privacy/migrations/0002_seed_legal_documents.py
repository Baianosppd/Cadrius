import hashlib

from django.db import migrations

from privacy import seed_texts


def seed(apps, schema_editor):
    LegalDocument = apps.get_model('privacy', 'LegalDocument')
    Subprocessor = apps.get_model('privacy', 'SubprocessorEntry')
    for kind, title, content in seed_texts.DOCUMENTS:
        LegalDocument.objects.get_or_create(
            kind=kind, version='1.0',
            defaults={
                'title': title, 'content_md': content, 'is_current': True, 'needs_legal_review': True,
                'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
            },
        )
    for name, country, purpose, categories in seed_texts.SUBPROCESSORS:
        Subprocessor.objects.get_or_create(
            name=name,
            defaults={
                'country': country, 'purpose': purpose, 'data_categories': categories,
                'international_transfer': not country.startswith('Brasil'),
                'safeguards': 'A formalizar (DPA/cláusulas-padrão) — pendente do jurídico.',
            },
        )


class Migration(migrations.Migration):
    dependencies = [('privacy', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
