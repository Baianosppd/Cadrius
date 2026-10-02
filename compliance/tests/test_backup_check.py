import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from compliance import checks


def _line(env, status, age_h, offsite):
    ts = (timezone.now() - timedelta(hours=age_h)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return f'{env} {status} {ts} file=x.gpg bytes=10 offsite={offsite} msg=ok\n'


class BackupCheckTests(TestCase):
    def _run(self, content):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'backup.status'
            f.write_text(content)
            with override_settings(BACKUP_STATUS_FILE=str(f)):
                return checks._backup()

    def test_recent_with_offsite_passes(self):
        self.assertEqual(self._run(_line('prod', 'ok', 2, 'true')).status, checks.PASS)

    def test_without_offsite_is_partial(self):
        self.assertEqual(self._run(_line('prod', 'ok', 2, 'false')).status, checks.PARTIAL)

    def test_stale_or_failed_fails(self):
        self.assertEqual(self._run(_line('prod', 'ok', 40, 'true')).status, checks.FAIL)
        self.assertEqual(self._run(_line('prod', 'failed', 1, 'false')).status, checks.FAIL)

    def test_ignores_staging_lines(self):
        self.assertNotEqual(self._run(_line('staging', 'ok', 1, 'true')).status, checks.PASS)
