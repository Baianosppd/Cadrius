# Generated manually for generic Trigger/Action model (Tarefa 1)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0004_appconnection_remove_integrationconfig_user_and_more'),
        ('workflows', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='trigger',
            name='app_connection',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='workflow_triggers',
                to='integrations.appconnection',
                verbose_name='Conexão de app',
            ),
        ),
        migrations.RenameField(
            model_name='trigger',
            old_name='config',
            new_name='payload_template',
        ),
        migrations.AddField(
            model_name='action',
            name='app_connection',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='workflow_actions',
                to='integrations.appconnection',
                verbose_name='Conexão de app',
            ),
        ),
        migrations.RenameField(
            model_name='action',
            old_name='config',
            new_name='payload_template',
        ),
    ]
