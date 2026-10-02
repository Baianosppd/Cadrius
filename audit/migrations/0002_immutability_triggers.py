from django.db import migrations

CREATE = """
CREATE OR REPLACE FUNCTION audit_block_mutation() RETURNS trigger AS $$
BEGIN
  -- O expurgo por retenção (audit.retention) liga esta flag, só dentro da sua transação.
  IF TG_OP = 'DELETE' AND current_setting('audit.allow_purge', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'audit_auditevent é imutável (append-only): % bloqueado', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditevent_immutable
  BEFORE UPDATE OR DELETE ON audit_auditevent
  FOR EACH ROW EXECUTE FUNCTION audit_block_mutation();

CREATE TRIGGER audit_auditevent_no_truncate
  BEFORE TRUNCATE ON audit_auditevent
  FOR EACH STATEMENT EXECUTE FUNCTION audit_block_mutation();
"""

DROP = """
DROP TRIGGER IF EXISTS audit_auditevent_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_auditevent_immutable ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_block_mutation();
"""


def apply_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(CREATE, params=None)


def drop_triggers(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(DROP, params=None)


class Migration(migrations.Migration):
    dependencies = [('audit', '0001_initial')]
    operations = [migrations.RunPython(apply_triggers, drop_triggers)]
