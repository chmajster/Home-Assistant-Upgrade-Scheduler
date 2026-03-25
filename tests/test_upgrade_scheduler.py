"""Unit tests for the Upgrade Scheduler add-on."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

# Make the src directory importable
SRC_DIR = os.path.join(
    os.path.dirname(__file__),
    "..", "upgrade_scheduler", "src"
)
sys.path.insert(0, os.path.abspath(SRC_DIR))


# ---------------------------------------------------------------------------
# config_manager
# ---------------------------------------------------------------------------

class TestConfigManager(unittest.TestCase):
    def _write_options(self, data: dict, tmp_dir: str) -> str:
        path = os.path.join(tmp_dir, "options.json")
        with open(path, "w") as fh:
            json.dump(data, fh)
        return path

    def test_defaults_when_no_file(self):
        with patch.dict(os.environ, {"OPTIONS_FILE": "/nonexistent/options.json"}):
            # Re-import to pick up the env override
            import importlib, config_manager
            importlib.reload(config_manager)
            cfg = config_manager.load_config()
        self.assertEqual(cfg.schedule_cron, "0 3 * * 0")
        self.assertTrue(cfg.update_core)
        self.assertEqual(cfg.backup_keep_last, 5)
        self.assertEqual(cfg.log_level, "info")

    def test_custom_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_options(
                {
                    "schedule_cron": "0 4 * * 1",
                    "update_core": False,
                    "backup_keep_last": 3,
                    "log_level": "debug",
                    "addon_exclude": ["addon_a", "addon_b"],
                },
                tmp,
            )
            with patch.dict(os.environ, {"OPTIONS_FILE": path}):
                import importlib, config_manager
                importlib.reload(config_manager)
                cfg = config_manager.load_config()
        self.assertEqual(cfg.schedule_cron, "0 4 * * 1")
        self.assertFalse(cfg.update_core)
        self.assertEqual(cfg.backup_keep_last, 3)
        self.assertEqual(cfg.log_level, "debug")
        self.assertEqual(cfg.addon_exclude, ["addon_a", "addon_b"])

    def test_invalid_json_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "options.json")
            with open(path, "w") as fh:
                fh.write("not json {{{")
            with patch.dict(os.environ, {"OPTIONS_FILE": path}):
                import importlib, config_manager
                importlib.reload(config_manager)
                cfg = config_manager.load_config()
        self.assertEqual(cfg.log_level, "info")

    def test_backup_keep_last_clamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_options({"backup_keep_last": 99}, tmp)
            with patch.dict(os.environ, {"OPTIONS_FILE": path}):
                import importlib, config_manager
                importlib.reload(config_manager)
                cfg = config_manager.load_config()
        self.assertEqual(cfg.backup_keep_last, 20)

    def test_invalid_log_level_defaults_to_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_options({"log_level": "verbose"}, tmp)
            with patch.dict(os.environ, {"OPTIONS_FILE": path}):
                import importlib, config_manager
                importlib.reload(config_manager)
                cfg = config_manager.load_config()
        self.assertEqual(cfg.log_level, "info")


# ---------------------------------------------------------------------------
# pre_checks
# ---------------------------------------------------------------------------

class TestPreCheckRunner(unittest.TestCase):
    def _make_client(
        self,
        supervisor_healthy=True,
        core_state="running",
        cpu_percent=10.0,
        mem_used=500,
        mem_total=2000,
    ):
        client = MagicMock()
        client.get_supervisor_info.return_value = {"healthy": supervisor_healthy}
        client.get_core_info.return_value = {"state": core_state}
        client.get_host_info.return_value = {
            "cpu_percent": cpu_percent,
            "memory": {"used": mem_used, "total": mem_total},
        }
        return client

    def test_all_checks_pass(self):
        from pre_checks import PreCheckRunner
        client = self._make_client()
        runner = PreCheckRunner(client, cpu_threshold=80, memory_threshold=80)
        result = runner.run_all()
        self.assertTrue(result.passed)
        self.assertEqual(result.failures, [])

    def test_supervisor_unhealthy_fails(self):
        from pre_checks import PreCheckRunner
        client = self._make_client(supervisor_healthy=False)
        runner = PreCheckRunner(client)
        result = runner.run_all()
        self.assertFalse(result.passed)
        self.assertTrue(any("unhealthy" in f for f in result.failures))

    def test_core_not_running_fails(self):
        from pre_checks import PreCheckRunner
        client = self._make_client(core_state="stopped")
        runner = PreCheckRunner(client)
        result = runner.run_all()
        self.assertFalse(result.passed)
        self.assertTrue(any("not running" in f for f in result.failures))

    def test_high_cpu_fails(self):
        from pre_checks import PreCheckRunner
        client = self._make_client(cpu_percent=95.0)
        runner = PreCheckRunner(client, cpu_threshold=80)
        result = runner.run_all()
        self.assertFalse(result.passed)
        self.assertTrue(any("CPU" in f for f in result.failures))

    def test_high_memory_fails(self):
        from pre_checks import PreCheckRunner
        # 1800/2000 = 90%
        client = self._make_client(mem_used=1800, mem_total=2000)
        runner = PreCheckRunner(client, memory_threshold=80)
        result = runner.run_all()
        self.assertFalse(result.passed)
        self.assertTrue(any("Memory" in f for f in result.failures))

    def test_api_error_is_captured(self):
        from pre_checks import PreCheckRunner
        from supervisor_api import SupervisorAPIError
        client = MagicMock()
        client.get_supervisor_info.side_effect = SupervisorAPIError("timeout")
        client.get_core_info.return_value = {"state": "running"}
        client.get_host_info.return_value = {}
        runner = PreCheckRunner(client)
        result = runner.run_all()
        self.assertFalse(result.passed)


# ---------------------------------------------------------------------------
# backup_manager
# ---------------------------------------------------------------------------

class TestBackupManager(unittest.TestCase):
    def test_create_backup_returns_slug(self):
        from backup_manager import BackupManager
        client = MagicMock()
        client.create_full_backup.return_value = "abc123"
        mgr = BackupManager(client, name_prefix="test", keep_last=5)
        slug = mgr.create_backup()
        self.assertEqual(slug, "abc123")
        client.create_full_backup.assert_called_once()

    def test_create_backup_returns_none_on_error(self):
        from backup_manager import BackupManager
        from supervisor_api import SupervisorAPIError
        client = MagicMock()
        client.create_full_backup.side_effect = SupervisorAPIError("err")
        mgr = BackupManager(client, name_prefix="test", keep_last=5)
        slug = mgr.create_backup()
        self.assertIsNone(slug)

    def test_enforce_retention_removes_old_backups(self):
        from backup_manager import BackupManager
        client = MagicMock()
        backups = [
            {"slug": f"s{i}", "name": f"test-2024010{i}", "date": f"2024-01-0{i}T00:00:00Z"}
            for i in range(1, 8)  # 7 backups
        ]
        client.list_backups.return_value = backups
        mgr = BackupManager(client, name_prefix="test", keep_last=3)
        mgr.enforce_retention()
        # Should have removed 4 oldest backups
        self.assertEqual(client.remove_backup.call_count, 4)

    def test_enforce_retention_keeps_all_when_within_limit(self):
        from backup_manager import BackupManager
        client = MagicMock()
        backups = [
            {"slug": f"s{i}", "name": f"test-backup-{i}", "date": f"2024-01-0{i}T00:00:00Z"}
            for i in range(1, 4)  # 3 backups
        ]
        client.list_backups.return_value = backups
        mgr = BackupManager(client, name_prefix="test", keep_last=5)
        mgr.enforce_retention()
        client.remove_backup.assert_not_called()

    def test_enforce_retention_ignores_unrelated_backups(self):
        from backup_manager import BackupManager
        client = MagicMock()
        backups = [
            {"slug": "s1", "name": "manual-backup", "date": "2024-01-01T00:00:00Z"},
            {"slug": "s2", "name": "test-2024-01-01", "date": "2024-01-01T00:00:00Z"},
        ]
        client.list_backups.return_value = backups
        mgr = BackupManager(client, name_prefix="test", keep_last=1)
        mgr.enforce_retention()
        # Only the "test-" prefixed backup is managed; none should be removed
        # since there's only 1 managed backup and keep_last=1
        client.remove_backup.assert_not_called()


# ---------------------------------------------------------------------------
# updater
# ---------------------------------------------------------------------------

class TestUpdater(unittest.TestCase):
    def _make_client(self, update_available=True):
        client = MagicMock()
        client.get_supervisor_info.return_value = {"update_available": update_available}
        client.get_core_info.return_value = {"update_available": update_available}
        client.get_addons.return_value = [
            {"slug": "addon_1", "name": "Addon One", "update_available": update_available},
            {"slug": "addon_2", "name": "Addon Two", "update_available": update_available},
        ]
        return client

    def test_updates_all_when_available(self):
        from updater import Updater
        client = self._make_client(update_available=True)
        u = Updater(client, update_core=True, update_supervisor=True, update_addons=True)
        report = u.run()
        self.assertTrue(report.core_updated)
        self.assertTrue(report.supervisor_updated)
        self.assertIn("Addon One", report.addons_updated)
        self.assertIn("Addon Two", report.addons_updated)
        self.assertTrue(report.success)

    def test_skips_when_no_update_available(self):
        from updater import Updater
        client = self._make_client(update_available=False)
        u = Updater(client, update_core=True, update_supervisor=True, update_addons=True)
        report = u.run()
        self.assertFalse(report.core_updated)
        self.assertFalse(report.supervisor_updated)
        self.assertEqual(report.addons_updated, [])
        self.assertTrue(report.success)

    def test_excluded_addon_is_skipped(self):
        from updater import Updater
        client = self._make_client(update_available=True)
        u = Updater(
            client,
            update_addons=True,
            addon_exclude=["addon_1"],
        )
        report = u.run()
        self.assertNotIn("Addon One", report.addons_updated)
        self.assertIn("Addon Two", report.addons_updated)

    def test_force_update_ignores_update_available(self):
        from updater import Updater
        client = self._make_client(update_available=False)
        u = Updater(client, update_core=True, update_supervisor=True, force_update=True)
        report = u.run()
        self.assertTrue(report.core_updated)
        self.assertTrue(report.supervisor_updated)

    def test_rollback_on_failure(self):
        from updater import Updater
        from supervisor_api import SupervisorAPIError
        client = self._make_client(update_available=True)
        client.update_core.side_effect = SupervisorAPIError("core failed")
        backup_mgr = MagicMock()
        backup_mgr.restore_backup.return_value = True
        u = Updater(
            client,
            backup_manager=backup_mgr,
            update_core=True,
            update_supervisor=False,
            update_addons=False,
            rollback_on_failure=True,
        )
        report = u.run(pre_backup_slug="slug_abc")
        self.assertFalse(report.success)
        self.assertTrue(report.rolled_back)
        backup_mgr.restore_backup.assert_called_once_with("slug_abc")

    def test_no_rollback_without_backup_slug(self):
        from updater import Updater
        from supervisor_api import SupervisorAPIError
        client = self._make_client(update_available=True)
        client.update_core.side_effect = SupervisorAPIError("fail")
        backup_mgr = MagicMock()
        u = Updater(
            client,
            backup_manager=backup_mgr,
            update_core=True,
            update_supervisor=False,
            update_addons=False,
            rollback_on_failure=True,
        )
        report = u.run(pre_backup_slug=None)
        self.assertFalse(report.rolled_back)
        backup_mgr.restore_backup.assert_not_called()

    def test_update_report_summary_no_updates(self):
        from updater import UpdateReport
        r = UpdateReport()
        self.assertIn("No updates", r.summary())

    def test_update_report_summary_with_updates(self):
        from updater import UpdateReport
        r = UpdateReport(
            core_updated=True,
            supervisor_updated=True,
            addons_updated=["MyAddon"],
        )
        s = r.summary()
        self.assertIn("Core updated", s)
        self.assertIn("Supervisor updated", s)
        self.assertIn("MyAddon", s)


# ---------------------------------------------------------------------------
# notifier
# ---------------------------------------------------------------------------

class TestNotifier(unittest.TestCase):
    def test_notify_success_sends_notification(self):
        from notifier import Notifier
        client = MagicMock()
        n = Notifier(client, notify_on_success=True, notify_on_failure=True)
        n.notify_success("All good")
        client.send_notification.assert_called_once()
        args = client.send_notification.call_args[0]
        self.assertIn("Successful", args[0])

    def test_notify_failure_sends_notification(self):
        from notifier import Notifier
        client = MagicMock()
        n = Notifier(client, notify_on_success=True, notify_on_failure=True)
        n.notify_failure("Something broke")
        client.send_notification.assert_called_once()
        args = client.send_notification.call_args[0]
        self.assertIn("Failed", args[0])

    def test_silent_mode_suppresses_notifications(self):
        from notifier import Notifier
        client = MagicMock()
        n = Notifier(client, notify_on_success=True, silent_mode=True)
        n.notify_success("Should not send")
        client.send_notification.assert_not_called()

    def test_notify_on_success_false_suppresses(self):
        from notifier import Notifier
        client = MagicMock()
        n = Notifier(client, notify_on_success=False, notify_on_failure=True)
        n.notify_success("Should not send")
        client.send_notification.assert_not_called()

    def test_notify_on_failure_false_suppresses(self):
        from notifier import Notifier
        client = MagicMock()
        n = Notifier(client, notify_on_success=True, notify_on_failure=False)
        n.notify_failure("Should not send")
        client.send_notification.assert_not_called()

    def test_api_error_does_not_propagate(self):
        from notifier import Notifier
        from supervisor_api import SupervisorAPIError
        client = MagicMock()
        client.send_notification.side_effect = SupervisorAPIError("network error")
        n = Notifier(client, notify_on_success=True)
        # Should not raise
        n.notify_success("test")


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------

class TestScheduler(unittest.TestCase):
    def test_invalid_cron_raises(self):
        from scheduler import Scheduler
        with self.assertRaises(ValueError):
            Scheduler("not-a-cron", lambda: None)

    def test_valid_cron_does_not_raise(self):
        from scheduler import Scheduler
        s = Scheduler("0 3 * * 0", lambda: None)
        self.assertIsNotNone(s)

    def test_job_called_when_due(self):
        """Verify that the job is executed when the scheduled time has passed."""
        from scheduler import Scheduler
        from datetime import datetime, timezone, timedelta

        job = MagicMock()

        # Patch _next_run_time to return a time slightly in the past
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        # Patch time.sleep to avoid actual sleeping and stop after first tick
        call_count = [0]

        def fake_sleep(_):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise StopIteration("stop loop")

        with patch("scheduler.Scheduler._next_run_time", return_value=past):
            with patch("scheduler.time.sleep", side_effect=fake_sleep):
                s = Scheduler("0 3 * * 0", job)
                try:
                    s.run_forever()
                except StopIteration:
                    pass
        job.assert_called()

    def test_job_exception_does_not_kill_loop(self):
        """Verify that an exception in the job does not propagate."""
        from scheduler import Scheduler
        from datetime import datetime, timezone, timedelta

        def bad_job():
            raise RuntimeError("oops")

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        call_count = [0]

        def fake_sleep(_):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise StopIteration

        with patch("scheduler.Scheduler._next_run_time", return_value=past):
            with patch("scheduler.time.sleep", side_effect=fake_sleep):
                s = Scheduler("0 3 * * 0", bad_job)
                try:
                    s.run_forever()
                except StopIteration:
                    pass  # expected – proves the loop survived the bad_job exception


if __name__ == "__main__":
    unittest.main()
