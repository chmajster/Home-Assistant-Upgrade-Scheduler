"""Configuration loading and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from ha_autoupgrade.constants import (
    CONFIG_SECRET_KEYS,
    DATA_DIR,
    DEFAULT_WEEKDAYS,
    OVERRIDE_OPTIONS_FILE,
)
from ha_autoupgrade.models import ActionCall
from ha_autoupgrade.utils.versioning import parse_mapping_entries

VALID_UPDATE_STRATEGIES = {"addons_last", "addons_first", "core_first"}
VALID_BACKUP_MODES = {"full", "partial"}
VALID_LOG_LEVELS = {"debug", "info", "warning", "error"}
VALID_WEEKDAYS = set(DEFAULT_WEEKDAYS)
VALID_UPDATE_TYPES = {"core", "supervisor", "os", "addons"}


class ConfigError(ValueError):
    """Raised when configuration is invalid."""


DEFAULT_OPTIONS: dict[str, Any] = {
    "log_level": "info",
    "json_logs": False,
    "dry_run": False,
    "notify_only_mode": False,
    "check_only_mode": False,
    "security_only_mode": False,
    "enabled_update_types": ["core", "supervisor", "os", "addons"],
    "update_strategy": "addons_last",
    "excluded_addons": [],
    "pinned_versions": [],
    "minimum_required_versions": [],
    "staged_rollout_enabled": False,
    "staged_rollout_percent": 100,
    "staged_rollout_seed": "default",
    "max_updates_per_run": 0,
    "delay_between_updates_seconds": 45,
    "create_backup": True,
    "backup_mode": "full",
    "backup_password": "",
    "backup_retention": 5,
    "backup_partial_addons": [],
    "rollback_on_failure": False,
    "schedule_check_interval_minutes": 60,
    "schedule_install_interval_minutes": 360,
    "schedule_check_cron": "",
    "schedule_install_cron": "",
    "schedule_check_weekday_time": "",
    "schedule_install_weekday_time": "sun@03:00",
    "schedule_allowed_weekdays": list(DEFAULT_WEEKDAYS),
    "schedule_jitter_seconds": 90,
    "maintenance_window": "22:00-06:00",
    "blackout_dates": [],
    "min_free_disk_mb": 1024,
    "max_cpu_load_1m": 5.0,
    "min_free_memory_mb": 256,
    "api_retry_max_attempts": 4,
    "api_retry_backoff_seconds": 2,
    "cooldown_minutes_after_failure": 120,
    "min_minutes_between_runs": 30,
    "safe_mode_failure_threshold": 3,
    "safe_mode_minutes": 240,
    "watchdog_enabled": False,
    "watchdog_timeout_minutes": 45,
    "ups_status_entity": "",
    "ups_required_state": "on",
    "approval_entity": "",
    "require_entity_states": [],
    "skip_if_someone_home_entity": "",
    "skip_if_media_playing_entity": "",
    "skip_if_critical_mode_entity": "",
    "skip_if_alarm_armed_away_entity": "",
    "skip_if_vacuum_cleaning_entity": "",
    "unstable_binary_sensor_entity": "",
    "maintenance_mode_service": "",
    "maintenance_mode_restore_service": "",
    "pre_update_services": [],
    "post_update_services": [],
    "pre_update_entities_on": [],
    "pre_update_entities_off": [],
    "post_update_restart_addons": [],
    "post_update_notify": True,
    "notification_enable_start": True,
    "notification_enable_success": True,
    "notification_enable_partial": True,
    "notification_enable_failure": True,
    "notification_enable_skip": True,
    "notify_persistent": True,
    "notify_services": [],
    "notify_webhook_url": "",
    "notify_webhook_token": "",
    "smtp_enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_to": "",
    "webhook_trigger_token": "",
    "export_redact_secrets": True,
}


def _parse_action_call(value: str) -> ActionCall:
    service, separator, raw_data = value.partition("|")
    service = service.strip()
    if "." not in service:
        raise ConfigError(f"Invalid service action: {value}")
    data: dict[str, Any] = {}
    if separator and raw_data.strip():
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError as err:
            raise ConfigError(f"Invalid JSON service payload: {value}") from err
        if not isinstance(data, dict):
            raise ConfigError(f"Service payload must be a JSON object: {value}")
    return ActionCall(service=service, data=data)


@dataclass(slots=True)
class AppConfig:
    raw_options: dict[str, Any]
    data_dir: Path = DATA_DIR
    log_level: str = "info"
    json_logs: bool = False
    dry_run: bool = False
    notify_only_mode: bool = False
    check_only_mode: bool = False
    security_only_mode: bool = False
    enabled_update_types: set[str] = field(
        default_factory=lambda: set(DEFAULT_OPTIONS["enabled_update_types"])
    )
    update_strategy: str = "addons_last"
    excluded_addons: set[str] = field(default_factory=set)
    pinned_versions: dict[str, str] = field(default_factory=dict)
    minimum_required_versions: dict[str, str] = field(default_factory=dict)
    staged_rollout_enabled: bool = False
    staged_rollout_percent: int = 100
    staged_rollout_seed: str = "default"
    max_updates_per_run: int = 0
    delay_between_updates_seconds: int = 45
    create_backup: bool = True
    backup_mode: str = "full"
    backup_password: str = ""
    backup_retention: int = 5
    backup_partial_addons: list[str] = field(default_factory=list)
    rollback_on_failure: bool = False
    schedule_check_interval_minutes: int = 60
    schedule_install_interval_minutes: int = 360
    schedule_check_cron: str = ""
    schedule_install_cron: str = ""
    schedule_check_weekday_time: str = ""
    schedule_install_weekday_time: str = "sun@03:00"
    schedule_allowed_weekdays: set[str] = field(default_factory=lambda: set(DEFAULT_WEEKDAYS))
    schedule_jitter_seconds: int = 90
    maintenance_window: str = "22:00-06:00"
    blackout_dates: list[str] = field(default_factory=list)
    min_free_disk_mb: int = 1024
    max_cpu_load_1m: float = 5.0
    min_free_memory_mb: int = 256
    api_retry_max_attempts: int = 4
    api_retry_backoff_seconds: int = 2
    cooldown_minutes_after_failure: int = 120
    min_minutes_between_runs: int = 30
    safe_mode_failure_threshold: int = 3
    safe_mode_minutes: int = 240
    watchdog_enabled: bool = False
    watchdog_timeout_minutes: int = 45
    ups_status_entity: str = ""
    ups_required_state: str = "on"
    approval_entity: str = ""
    require_entity_states: dict[str, str] = field(default_factory=dict)
    skip_if_someone_home_entity: str = ""
    skip_if_media_playing_entity: str = ""
    skip_if_critical_mode_entity: str = ""
    skip_if_alarm_armed_away_entity: str = ""
    skip_if_vacuum_cleaning_entity: str = ""
    unstable_binary_sensor_entity: str = ""
    maintenance_mode_service: str = ""
    maintenance_mode_restore_service: str = ""
    pre_update_services: list[ActionCall] = field(default_factory=list)
    post_update_services: list[ActionCall] = field(default_factory=list)
    pre_update_entities_on: list[str] = field(default_factory=list)
    pre_update_entities_off: list[str] = field(default_factory=list)
    post_update_restart_addons: list[str] = field(default_factory=list)
    post_update_notify: bool = True
    notification_enable_start: bool = True
    notification_enable_success: bool = True
    notification_enable_partial: bool = True
    notification_enable_failure: bool = True
    notification_enable_skip: bool = True
    notify_persistent: bool = True
    notify_services: list[str] = field(default_factory=list)
    notify_webhook_url: str = ""
    notify_webhook_token: str = ""
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    webhook_trigger_token: str = ""
    export_redact_secrets: bool = True

    @classmethod
    def from_dict(cls, user_options: dict[str, Any], data_dir: Path = DATA_DIR) -> "AppConfig":
        merged = deepcopy(DEFAULT_OPTIONS)
        merged.update(user_options)

        log_level = str(merged["log_level"]).lower()
        if log_level not in VALID_LOG_LEVELS:
            raise ConfigError(f"Unsupported log level: {log_level}")

        enabled_update_types = {entry.lower() for entry in merged["enabled_update_types"]}
        if not enabled_update_types.issubset(VALID_UPDATE_TYPES):
            raise ConfigError("enabled_update_types contains unsupported values")

        update_strategy = str(merged["update_strategy"]).lower()
        if update_strategy not in VALID_UPDATE_STRATEGIES:
            raise ConfigError(f"Unsupported update_strategy: {update_strategy}")

        backup_mode = str(merged["backup_mode"]).lower()
        if backup_mode not in VALID_BACKUP_MODES:
            raise ConfigError(f"Unsupported backup_mode: {backup_mode}")

        allowed_weekdays = {entry.lower() for entry in merged["schedule_allowed_weekdays"]}
        if not allowed_weekdays.issubset(VALID_WEEKDAYS):
            raise ConfigError("schedule_allowed_weekdays contains unsupported values")

        rollout_percent = int(merged["staged_rollout_percent"])
        if rollout_percent < 0 or rollout_percent > 100:
            raise ConfigError("staged_rollout_percent must be between 0 and 100")

        require_entity_states = parse_mapping_entries(
            merged["require_entity_states"], "require_entity_states"
        )

        pre_update_services = [_parse_action_call(item) for item in merged["pre_update_services"]]
        post_update_services = [_parse_action_call(item) for item in merged["post_update_services"]]

        config = cls(
            raw_options=merged,
            data_dir=data_dir,
            log_level=log_level,
            json_logs=bool(merged["json_logs"]),
            dry_run=bool(merged["dry_run"]),
            notify_only_mode=bool(merged["notify_only_mode"]),
            check_only_mode=bool(merged["check_only_mode"]),
            security_only_mode=bool(merged["security_only_mode"]),
            enabled_update_types=enabled_update_types,
            update_strategy=update_strategy,
            excluded_addons={item.lower() for item in merged["excluded_addons"]},
            pinned_versions=parse_mapping_entries(merged["pinned_versions"], "pinned_versions"),
            minimum_required_versions=parse_mapping_entries(
                merged["minimum_required_versions"], "minimum_required_versions"
            ),
            staged_rollout_enabled=bool(merged["staged_rollout_enabled"]),
            staged_rollout_percent=rollout_percent,
            staged_rollout_seed=str(merged["staged_rollout_seed"]),
            max_updates_per_run=int(merged["max_updates_per_run"]),
            delay_between_updates_seconds=int(merged["delay_between_updates_seconds"]),
            create_backup=bool(merged["create_backup"]),
            backup_mode=backup_mode,
            backup_password=str(merged["backup_password"] or ""),
            backup_retention=int(merged["backup_retention"]),
            backup_partial_addons=list(merged["backup_partial_addons"]),
            rollback_on_failure=bool(merged["rollback_on_failure"]),
            schedule_check_interval_minutes=int(merged["schedule_check_interval_minutes"]),
            schedule_install_interval_minutes=int(merged["schedule_install_interval_minutes"]),
            schedule_check_cron=str(merged["schedule_check_cron"] or ""),
            schedule_install_cron=str(merged["schedule_install_cron"] or ""),
            schedule_check_weekday_time=str(merged["schedule_check_weekday_time"] or ""),
            schedule_install_weekday_time=str(merged["schedule_install_weekday_time"] or ""),
            schedule_allowed_weekdays=allowed_weekdays,
            schedule_jitter_seconds=int(merged["schedule_jitter_seconds"]),
            maintenance_window=str(merged["maintenance_window"]),
            blackout_dates=list(merged["blackout_dates"]),
            min_free_disk_mb=int(merged["min_free_disk_mb"]),
            max_cpu_load_1m=float(merged["max_cpu_load_1m"]),
            min_free_memory_mb=int(merged["min_free_memory_mb"]),
            api_retry_max_attempts=int(merged["api_retry_max_attempts"]),
            api_retry_backoff_seconds=int(merged["api_retry_backoff_seconds"]),
            cooldown_minutes_after_failure=int(merged["cooldown_minutes_after_failure"]),
            min_minutes_between_runs=int(merged["min_minutes_between_runs"]),
            safe_mode_failure_threshold=int(merged["safe_mode_failure_threshold"]),
            safe_mode_minutes=int(merged["safe_mode_minutes"]),
            watchdog_enabled=bool(merged["watchdog_enabled"]),
            watchdog_timeout_minutes=int(merged["watchdog_timeout_minutes"]),
            ups_status_entity=str(merged["ups_status_entity"]),
            ups_required_state=str(merged["ups_required_state"]),
            approval_entity=str(merged["approval_entity"]),
            require_entity_states=require_entity_states,
            skip_if_someone_home_entity=str(merged["skip_if_someone_home_entity"]),
            skip_if_media_playing_entity=str(merged["skip_if_media_playing_entity"]),
            skip_if_critical_mode_entity=str(merged["skip_if_critical_mode_entity"]),
            skip_if_alarm_armed_away_entity=str(merged["skip_if_alarm_armed_away_entity"]),
            skip_if_vacuum_cleaning_entity=str(merged["skip_if_vacuum_cleaning_entity"]),
            unstable_binary_sensor_entity=str(merged["unstable_binary_sensor_entity"]),
            maintenance_mode_service=str(merged["maintenance_mode_service"]),
            maintenance_mode_restore_service=str(merged["maintenance_mode_restore_service"]),
            pre_update_services=pre_update_services,
            post_update_services=post_update_services,
            pre_update_entities_on=list(merged["pre_update_entities_on"]),
            pre_update_entities_off=list(merged["pre_update_entities_off"]),
            post_update_restart_addons=list(merged["post_update_restart_addons"]),
            post_update_notify=bool(merged["post_update_notify"]),
            notification_enable_start=bool(merged["notification_enable_start"]),
            notification_enable_success=bool(merged["notification_enable_success"]),
            notification_enable_partial=bool(merged["notification_enable_partial"]),
            notification_enable_failure=bool(merged["notification_enable_failure"]),
            notification_enable_skip=bool(merged["notification_enable_skip"]),
            notify_persistent=bool(merged["notify_persistent"]),
            notify_services=list(merged["notify_services"]),
            notify_webhook_url=str(merged["notify_webhook_url"]),
            notify_webhook_token=str(merged["notify_webhook_token"]),
            smtp_enabled=bool(merged["smtp_enabled"]),
            smtp_host=str(merged["smtp_host"]),
            smtp_port=int(merged["smtp_port"]),
            smtp_username=str(merged["smtp_username"]),
            smtp_password=str(merged["smtp_password"]),
            smtp_from=str(merged["smtp_from"]),
            smtp_to=str(merged["smtp_to"]),
            webhook_trigger_token=str(merged["webhook_trigger_token"]),
            export_redact_secrets=bool(merged["export_redact_secrets"]),
        )
        config.validate()
        return config

    def validate(self) -> None:
        for name in (
            "schedule_check_interval_minutes",
            "schedule_install_interval_minutes",
            "backup_retention",
            "min_free_disk_mb",
            "min_free_memory_mb",
            "api_retry_max_attempts",
            "api_retry_backoff_seconds",
            "cooldown_minutes_after_failure",
            "min_minutes_between_runs",
            "safe_mode_failure_threshold",
            "safe_mode_minutes",
            "delay_between_updates_seconds",
            "watchdog_timeout_minutes",
        ):
            if getattr(self, name) < 0:
                raise ConfigError(f"{name} must be >= 0")
        if self.smtp_enabled and (not self.smtp_host or not self.smtp_from or not self.smtp_to):
            raise ConfigError("SMTP is enabled but smtp_host/smtp_from/smtp_to are incomplete")

    def update_type_enabled(self, component_type: str) -> bool:
        normalized = "addons" if component_type == "addon" else component_type
        return normalized in self.enabled_update_types

    def notification_enabled(self, event_name: str) -> bool:
        mapping = {
            "start": self.notification_enable_start,
            "success": self.notification_enable_success,
            "partial": self.notification_enable_partial,
            "failure": self.notification_enable_failure,
            "skip": self.notification_enable_skip,
        }
        return mapping.get(event_name, True)

    def to_options_dict(self, redact_secrets: bool = False) -> dict[str, Any]:
        options = deepcopy(self.raw_options)
        if redact_secrets:
            for key in CONFIG_SECRET_KEYS:
                if key in options and options[key]:
                    options[key] = "***REDACTED***"
        return options


def load_config(data_dir: Path = DATA_DIR) -> AppConfig:
    options_path = data_dir / "options.json"
    payload = deepcopy(DEFAULT_OPTIONS)
    if options_path.exists():
        payload.update(json.loads(options_path.read_text(encoding="utf-8")))
    if OVERRIDE_OPTIONS_FILE.exists():
        payload.update(json.loads(OVERRIDE_OPTIONS_FILE.read_text(encoding="utf-8")))
    return AppConfig.from_dict(payload, data_dir=data_dir)
