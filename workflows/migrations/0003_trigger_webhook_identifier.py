# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workflows', '0002_alter_action_options_alter_workflow_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='trigger',
            name='webhook_identifier',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Chave única em POST /api/webhooks/<identifier>/',
                max_length=128,
                null=True,
                unique=True,
            ),
        ),
    ]
