"""CAD-152: cifra e indexa os nomes de cliente já existentes (ver accounts/migrations/0012_backfill_pii.py)."""
from django.db import migrations


def backfill(apps, schema_editor):
    from core.pii import search_tokens

    ClientDocument = apps.get_model('documents', 'ClientDocument')
    for link in ClientDocument.objects.all().iterator():
        link.nome_cliente_idx = search_tokens('client.name', link.nome_cliente)
        link.save(update_fields=['nome_cliente', 'nome_cliente_idx'])


class Migration(migrations.Migration):
    dependencies = [('documents', '0005_encrypt_pii')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
