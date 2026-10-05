"""Grupo da área Suporte (CAD-171). A TI atribui pela tela Equipe Cadrius."""
from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name='Cadrius Suporte')


def backwards(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name='Cadrius Suporte').delete()


class Migration(migrations.Migration):
    dependencies = [('backoffice', '0002_fiscal_group')]
    operations = [migrations.RunPython(forwards, backwards)]
