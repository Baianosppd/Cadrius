"""Política de Privacidade 2.0: seção "Dados de usuários do Google" pedida na verificação do app OAuth.
Vira a versão vigente (quem aceitou a 1.0 confirma a nova no próximo acesso). A descrição do Google na lista de
suboperadores passa a citar a Agenda e o Drive."""
import hashlib

from django.db import migrations

from privacy import seed_texts

GOOGLE_OLD = 'Google (Gemini, Login, Sheets)'


def publish(apps, schema_editor):
    LegalDocument = apps.get_model('privacy', 'LegalDocument')
    Subprocessor = apps.get_model('privacy', 'SubprocessorEntry')
    content = seed_texts.PRIVACY_V2
    doc, created = LegalDocument.objects.get_or_create(
        kind='privacy', version='2.0',
        defaults={'title': 'Política de Privacidade', 'content_md': content, 'requires_reconsent': True,
                  'needs_legal_review': True, 'content_sha256': hashlib.sha256(content.encode()).hexdigest()},
    )
    if created:  # uma 2.0 feita à mão no admin fica como está (o texto publicado é imutável)
        LegalDocument.objects.filter(kind='privacy').exclude(pk=doc.pk).update(is_current=False)
        LegalDocument.objects.filter(pk=doc.pk).update(is_current=True)
    Subprocessor.objects.filter(name=GOOGLE_OLD).update(
        name='Google (login, Agenda, Drive e Gemini)',
        purpose='Login com Google, Google Agenda e Google Drive autorizados pelo usuário e IA (Gemini, só conta paga para dados sensíveis)',
    )


def unpublish(apps, schema_editor):
    LegalDocument = apps.get_model('privacy', 'LegalDocument')
    Subprocessor = apps.get_model('privacy', 'SubprocessorEntry')
    v2 = LegalDocument.objects.filter(kind='privacy', version='2.0', consents__isnull=True)
    if v2.exists():
        v2.delete()
        LegalDocument.objects.filter(kind='privacy', version='1.0').update(is_current=True)
    Subprocessor.objects.filter(name='Google (login, Agenda, Drive e Gemini)').update(name=GOOGLE_OLD)


class Migration(migrations.Migration):
    dependencies = [('privacy', '0002_seed_legal_documents')]
    operations = [migrations.RunPython(publish, unpublish)]
