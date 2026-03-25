"""Main entry point for Home Assistant Upgrade Scheduler.

Wires together all subsystems:
  1. Configuration loading
  2. Logging setup
  3. Supervisor API client
  4. Pre-check runner
  5. Backup manager
  6. Updater
  7. Notifier
  8. Scheduler (blocking event loop)
"""

import logging
import sys
from typing import Optional

from config_manager import load_config, Config
from supervisor_api import SupervisorClient
from pre_checks import PreCheckRunner
from backup_manager import BackupManager
from updater import Updater
from notifier import Notifier
from scheduler import Scheduler


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


# ---------------------------------------------------------------------------
# Update job
# ---------------------------------------------------------------------------

def build_update_job(
    config: Config,
    client: SupervisorClient,
    pre_check_runner: PreCheckRunner,
    backup_mgr: BackupManager,
    updater: Updater,
    notifier: Notifier,
):
    """Return the callable that runs one full update cycle."""

    def run_update() -> None:
        logger = logging.getLogger("update_job")
        logger.info("=== Update run started ===")

        # 1. Pre-checks
        if config.pre_check_enabled:
            result = pre_check_runner.run_all()
            if not result.passed:
                msg = f"Pre-checks failed; aborting update. {result}"
                logger.warning(msg)
                notifier.notify_failure(msg)
                return

        # 2. Backup
        backup_slug: Optional[str] = None
        if config.backup_before_update:
            backup_slug = backup_mgr.create_backup()
            if backup_slug is None and not config.force_update:
                msg = "Backup creation failed; aborting update (force_update is off)."
                logger.error(msg)
                notifier.notify_failure(msg)
                return

        # 3. Apply updates
        report = updater.run(pre_backup_slug=backup_slug)
        logger.info("Update run finished: %s", report.summary())

        # 4. Enforce backup retention
        if config.backup_before_update:
            backup_mgr.enforce_retention()

        # 5. Notify
        if report.success:
            notifier.notify_success(report.summary())
        else:
            notifier.notify_failure(report.summary())

        logger.info("=== Update run complete ===")

    return run_update


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()
    setup_logging(config.log_level)
    logger = logging.getLogger("main")

    logger.info("Home Assistant Upgrade Scheduler starting up.")
    logger.info(
        "Config: cron='%s', core=%s, supervisor=%s, addons=%s, "
        "backup=%s, pre_checks=%s, rollback=%s",
        config.schedule_cron,
        config.update_core,
        config.update_supervisor,
        config.update_addons,
        config.backup_before_update,
        config.pre_check_enabled,
        config.rollback_on_failure,
    )

    client = SupervisorClient()

    pre_check_runner = PreCheckRunner(
        client,
        cpu_threshold=config.pre_check_cpu_threshold,
        memory_threshold=config.pre_check_memory_threshold,
    )

    backup_mgr = BackupManager(
        client,
        name_prefix=config.backup_name_prefix,
        keep_last=config.backup_keep_last,
    )

    updater = Updater(
        client,
        backup_manager=backup_mgr,
        update_core=config.update_core,
        update_supervisor=config.update_supervisor,
        update_addons=config.update_addons,
        addon_exclude=config.addon_exclude,
        force_update=config.force_update,
        rollback_on_failure=config.rollback_on_failure,
    )

    notifier = Notifier(
        client,
        notify_on_success=config.notify_on_success,
        notify_on_failure=config.notify_on_failure,
        silent_mode=config.silent_mode,
    )

    update_job = build_update_job(
        config, client, pre_check_runner, backup_mgr, updater, notifier
    )

    try:
        scheduler = Scheduler(config.schedule_cron, update_job)
    except ValueError as exc:
        logger.critical("Invalid schedule: %s", exc)
        sys.exit(1)

    scheduler.run_forever()


if __name__ == "__main__":
    main()
