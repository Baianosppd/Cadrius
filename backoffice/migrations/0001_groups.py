"""Cria os grupos das áreas e mantém o acesso de quem já era equipe (is_staff) antes da separação por área."""
from django.db import migrations

GROUPS = ('Cadrius TI', 'Cadrius Financeiro')


def forwards(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model('accounts', 'CustomUser')
    groups = [Group.objects.get_or_create(name=n)[0] for n in GROUPS]
    for user in User.objects.filter(is_staff=True, is_active=True, is_superuser=False):
        user.groups.add(*groups)


def backwards(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [('auth', '0012_alter_user_first_name_max_length'), ('accounts', '0012_backfill_pii')]
    operations = [migrations.RunPython(forwards, backwards)]
