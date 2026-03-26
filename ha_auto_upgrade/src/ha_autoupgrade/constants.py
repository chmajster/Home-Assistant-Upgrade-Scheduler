"""Application-wide constants."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "HA AutoUpgrade"
APP_SLUG = "ha_auto_upgrade"
APP_VERSION = "1.0.15"
STATE_SCHEMA_VERSION = 1
HISTORY_RETENTION = 1000
RECENT_LOG_BUFFER_SIZE = 250
BACKUP_NAME_PREFIX = "[HA AutoUpgrade]"
DEFAULT_SUPERVISOR_URL = "http://supervisor"
DEFAULT_CORE_API_URL = f"{DEFAULT_SUPERVISOR_URL}/core/api"
DATA_DIR = Path(os.getenv("HA_AUTOUPGRADE_DATA_DIR", "/data"))
STATE_FILE = DATA_DIR / "state.json"
HISTORY_FILE = DATA_DIR / "history.jsonl"
LOCK_FILE = DATA_DIR / "runtime.lock"
EXPORT_DIR = DATA_DIR / "exports"
IMPORT_DIR = DATA_DIR / "imports"
OVERRIDE_OPTIONS_FILE = DATA_DIR / "runtime_overrides.json"
APP_ROOT = Path(__file__).resolve().parents[2]
TRANSLATIONS_DIR = APP_ROOT / "translations"
WEB_PORT = 8099
ALLOWED_DASHBOARD_IPS = {"127.0.0.1", "::1", "172.30.32.2"}
ALLOWED_DASHBOARD_PREFIXES = ("172.30.",)
DEFAULT_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SUPPORTED_UPDATE_TYPES = {"core", "supervisor", "os", "addon"}
CONFIG_SECRET_KEYS = {
    "backup_password",
    "smtp_password",
    "notify_webhook_token",
    "webhook_trigger_token",
}
