"""Grupo da área Fiscal (CAD-170). Ninguém entra nele automaticamente: a TI atribui pela Gestão ou por cadrius_staff."""
from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name='Cadrius Fiscal')


def backwards(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name='Cadrius Fiscal').delete()


class Migration(migrations.Migration):
    dependencies = [('backoffice', '0001_groups')]
    operations = [migrations.RunPython(forwards, backwards)]
