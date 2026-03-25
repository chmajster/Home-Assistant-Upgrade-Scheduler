"""Configuration manager for Home Assistant Upgrade Scheduler.

Reads /data/options.json (written by the Supervisor from config.yaml schema)
and exposes a typed, validated Config object to the rest of the application.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import List

OPTIONS_FILE = os.environ.get("OPTIONS_FILE", "/data/options.json")

logger = logging.getLogger(__name__)


@dataclass
class Config:
    # Scheduling
    schedule_cron: str = "0 3 * * 0"

    # What to update
    update_core: bool = True
    update_supervisor: bool = True
    update_addons: bool = True
    addon_exclude: List[str] = field(default_factory=list)

    # Backup settings
    backup_before_update: bool = True
    backup_name_prefix: str = "upgrade-scheduler"
    backup_keep_last: int = 5

    # Pre-check settings
    pre_check_enabled: bool = True
    pre_check_cpu_threshold: int = 80
    pre_check_memory_threshold: int = 80

    # Update behaviour
    force_update: bool = False
    silent_mode: bool = False

    # Notifications
    notify_on_success: bool = True
    notify_on_failure: bool = True

    # Rollback
    rollback_on_failure: bool = False

    # Logging
    log_level: str = "info"


def load_config() -> Config:
    """Load configuration from the options file; fall back to defaults."""
    if not os.path.exists(OPTIONS_FILE):
        logger.warning("Options file not found at %s; using defaults.", OPTIONS_FILE)
        return Config()

    try:
        with open(OPTIONS_FILE, "r", encoding="utf-8") as fh:
            raw: dict = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to read options file: %s; using defaults.", exc)
        return Config()

    cfg = Config()

    # --- scheduling ---
    cfg.schedule_cron = str(raw.get("schedule_cron", cfg.schedule_cron))

    # --- what to update ---
    cfg.update_core = bool(raw.get("update_core", cfg.update_core))
    cfg.update_supervisor = bool(raw.get("update_supervisor", cfg.update_supervisor))
    cfg.update_addons = bool(raw.get("update_addons", cfg.update_addons))
    cfg.addon_exclude = list(raw.get("addon_exclude", cfg.addon_exclude))

    # --- backup ---
    cfg.backup_before_update = bool(
        raw.get("backup_before_update", cfg.backup_before_update)
    )
    cfg.backup_name_prefix = str(
        raw.get("backup_name_prefix", cfg.backup_name_prefix)
    )
    keep_last = int(raw.get("backup_keep_last", cfg.backup_keep_last))
    cfg.backup_keep_last = max(1, min(20, keep_last))

    # --- pre-checks ---
    cfg.pre_check_enabled = bool(
        raw.get("pre_check_enabled", cfg.pre_check_enabled)
    )
    cpu_threshold = int(raw.get("pre_check_cpu_threshold", cfg.pre_check_cpu_threshold))
    cfg.pre_check_cpu_threshold = max(1, min(100, cpu_threshold))
    mem_threshold = int(
        raw.get("pre_check_memory_threshold", cfg.pre_check_memory_threshold)
    )
    cfg.pre_check_memory_threshold = max(1, min(100, mem_threshold))

    # --- update behaviour ---
    cfg.force_update = bool(raw.get("force_update", cfg.force_update))
    cfg.silent_mode = bool(raw.get("silent_mode", cfg.silent_mode))

    # --- notifications ---
    cfg.notify_on_success = bool(raw.get("notify_on_success", cfg.notify_on_success))
    cfg.notify_on_failure = bool(raw.get("notify_on_failure", cfg.notify_on_failure))

    # --- rollback ---
    cfg.rollback_on_failure = bool(
        raw.get("rollback_on_failure", cfg.rollback_on_failure)
    )

    # --- logging ---
    valid_levels = {"debug", "info", "warning", "error"}
    log_level = str(raw.get("log_level", cfg.log_level)).lower()
    cfg.log_level = log_level if log_level in valid_levels else "info"

    return cfg
