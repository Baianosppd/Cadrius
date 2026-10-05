"""Grupo da área Marketing (CAD-174). A TI atribui pela tela Equipe Cadrius."""
from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name='Cadrius Marketing')


def backwards(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name='Cadrius Marketing').delete()


class Migration(migrations.Migration):
    dependencies = [('backoffice', '0003_support_group')]
    operations = [migrations.RunPython(forwards, backwards)]
