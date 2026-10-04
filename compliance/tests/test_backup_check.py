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


class OffsiteAndRestoreChecksTests(TestCase):
    def _run(self, fn, content):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'backup.status'
            f.write_text(content)
            with override_settings(BACKUP_STATUS_FILE=str(f)):
                return fn()

    def test_offsite_verified(self):
        self.assertEqual(self._run(checks._offsite_verified, _line('offsite-check-prod', 'ok', 5, 'true')).status, checks.PASS)
        self.assertEqual(self._run(checks._offsite_verified, _line('offsite-check-prod', 'failed', 5, 'false')).status, checks.FAIL)
        self.assertEqual(self._run(checks._offsite_verified, _line('offsite-check-prod', 'ok', 50, 'true')).status, checks.FAIL)
        self.assertNotEqual(self._run(checks._offsite_verified, _line('prod', 'ok', 1, 'true')).status, checks.PASS)

    def test_restore_drill(self):
        self.assertEqual(self._run(checks._restore_drill, _line('restore-test-prod', 'ok', 24 * 3, 'false')).status, checks.PASS)
        self.assertEqual(self._run(checks._restore_drill, _line('restore-test-prod', 'ok', 24 * 12, 'false')).status, checks.FAIL)
        self.assertEqual(self._run(checks._restore_drill, _line('restore-test-prod', 'failed', 1, 'false')).status, checks.FAIL)
