"""Configuration loading and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

from ha_autoupgrade.constants import (
    CONFIG_SECRET_KEYS,
    DATA_DIR,
    DEFAULT_WEEKDAYS,
    OVERRIDE_OPTIONS_FILE,
)
from ha_autoupgrade.models import ActionCall
from ha_autoupgrade.utils.dates import parse_hhmm, parse_iso_datetime
from ha_autoupgrade.utils.versioning import parse_mapping_entries

VALID_UPDATE_STRATEGIES = {"addons_last", "addons_first", "core_first"}
VALID_BACKUP_MODES = {"full", "partial"}
VALID_LOG_LEVELS = {"debug", "info", "warning", "error"}
VALID_SCHEDULE_FREQUENCIES = {"", "daily", "weekly", "monthly", "once"}
VALID_WEEKDAYS = set(DEFAULT_WEEKDAYS)
VALID_UPDATE_TYPES = {"core", "supervisor", "os", "addons"}
FULL_DAY_MAINTENANCE_WINDOW = "00:00-23:59"
WEEKDAY_ALIASES = {
    "mon": "mon",
    "monday": "mon",
    "pon": "mon",
    "poniedzialek": "mon",
    "tue": "tue",
    "tuesday": "tue",
    "wt": "tue",
    "wtorek": "tue",
    "wed": "wed",
    "wednesday": "wed",
    "sr": "wed",
    "sroda": "wed",
    "thu": "thu",
    "thursday": "thu",
    "czw": "thu",
    "czwartek": "thu",
    "fri": "fri",
    "friday": "fri",
    "pt": "fri",
    "piatek": "fri",
    "sat": "sat",
    "saturday": "sat",
    "sob": "sat",
    "sobota": "sat",
    "sun": "sun",
    "sunday": "sun",
    "nd": "sun",
    "ndz": "sun",
    "niedziela": "sun",
}
ALL_DAYS_TOKENS = {"all", "daily", "everyday", "codziennie", "wszystkie"}
DEFAULT_FALLBACK_TOKENS = {"*", "default", "auto"}
SCHEDULE_FREQUENCY_ALIASES = {
    "daily": "daily",
    "day": "daily",
    "codziennie": "daily",
    "weekly": "weekly",
    "week": "weekly",
    "tygodniowo": "weekly",
    "monthly": "monthly",
    "month": "monthly",
    "miesiecznie": "monthly",
    "once": "once",
    "onetime": "once",
    "one-time": "once",
    "jednorazowo": "once",
}


class ConfigError(ValueError):
    """Raised when configuration is invalid."""


DEFAULT_OPTIONS: dict[str, Any] = {
    "check_interval_minutes": 60,
    "install_days": "sun",
    "install_hour": "03:00",
    "schedule_install_frequency": "",
    "schedule_install_monthday": 1,
    "schedule_install_once_at": "",
    "schedule_install_time_range_end": "",
    "auto_install": False,
    "create_backup": True,
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


def _ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


def _parse_install_days(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        raw_tokens = [str(item) for item in value]
    else:
        raw_tokens = re.split(r"[\s,;]+", str(value).strip())
    normalized_days: list[str] = []
    for token in raw_tokens:
        folded = _ascii_fold(token)
        if not folded:
            continue
        if folded in DEFAULT_FALLBACK_TOKENS:
            return ()
        if folded in ALL_DAYS_TOKENS:
            return tuple(DEFAULT_WEEKDAYS)
        weekday = WEEKDAY_ALIASES.get(folded)
        if weekday is None:
            raise ConfigError(f"Unsupported weekday in {field_name}: {token}")
        if weekday not in normalized_days:
            normalized_days.append(weekday)
    return tuple(normalized_days)


def _normalize_install_hour(value: Any, field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw or _ascii_fold(raw) in DEFAULT_FALLBACK_TOKENS:
        return ""
    parsed = parse_hhmm(raw)
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _normalize_schedule_frequency(
    value: Any,
    *,
    install_days: tuple[str, ...],
    schedule_install_cron: str,
    schedule_install_once_at: str,
) -> str:
    folded = _ascii_fold(str(value or ""))
    if not folded or folded in DEFAULT_FALLBACK_TOKENS:
        if schedule_install_once_at:
            return "once"
        if schedule_install_cron:
            return ""
        return "daily" if tuple(install_days) == tuple(DEFAULT_WEEKDAYS) else "weekly"
    frequency = SCHEDULE_FREQUENCY_ALIASES.get(folded)
    if frequency is None:
        raise ConfigError(f"Unsupported schedule_install_frequency: {value}")
    return frequency


def _normalize_schedule_monthday(value: Any) -> int:
    raw = str(value or "").strip()
    if not raw or _ascii_fold(raw) in DEFAULT_FALLBACK_TOKENS:
        return 1
    try:
        day = int(raw)
    except ValueError as err:
        raise ConfigError(f"Invalid schedule_install_monthday: {value}") from err
    if day < 1 or day > 31:
        raise ConfigError("schedule_install_monthday must be between 1 and 31")
    return day


def _normalize_schedule_once_at(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or _ascii_fold(raw) in DEFAULT_FALLBACK_TOKENS:
        return ""
    parsed = parse_iso_datetime(raw)
    if parsed is None:
        return ""
    return parsed.isoformat()


def _infer_time_range_end(
    explicit_end: Any,
    maintenance_window: Any,
    install_hour: str,
) -> str:
    normalized_end = _normalize_install_hour(explicit_end, "schedule_install_time_range_end")
    if normalized_end:
        return normalized_end
    raw_window = str(maintenance_window or "").strip()
    if not raw_window or raw_window == FULL_DAY_MAINTENANCE_WINDOW or "-" not in raw_window:
        return ""
    start_raw, end_raw = raw_window.split("-", maxsplit=1)
    normalized_start = _normalize_install_hour(start_raw, "maintenance_window")
    normalized_end = _normalize_install_hour(end_raw, "maintenance_window")
    if normalized_start == install_hour and normalized_end != install_hour:
        return normalized_end
    return ""


def _split_legacy_weekday_time(value: str) -> tuple[str, str]:
    if _ascii_fold(value) in DEFAULT_FALLBACK_TOKENS:
        return "", ""
    weekday, separator, hour = value.partition("@")
    if not separator:
        raise ConfigError(f"Invalid legacy weekday/time value: {value}")
    weekdays = _parse_install_days(weekday, "schedule_install_weekday_time")
    if len(weekdays) != 1:
        raise ConfigError("schedule_install_weekday_time must contain exactly one weekday")
    return weekdays[0], _normalize_install_hour(hour, "schedule_install_weekday_time")


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
    check_interval_minutes: int = 60
    install_days: tuple[str, ...] = field(default_factory=lambda: ("sun",))
    install_hour: str = "03:00"
    schedule_install_frequency: str = ""
    schedule_install_monthday: int = 1
    schedule_install_once_at: str = ""
    schedule_install_time_range_end: str = ""
    auto_install: bool = False
    create_backup: bool = True
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

        install_days_input = user_options.get("install_days", merged["install_days"])
        install_hour_input = user_options.get("install_hour", merged["install_hour"])
        legacy_schedule_input = str(
            user_options.get("schedule_install_weekday_time", merged["schedule_install_weekday_time"]) or ""
        ).strip()
        if "install_days" not in user_options and "install_hour" not in user_options and legacy_schedule_input:
            install_days_input, install_hour_input = _split_legacy_weekday_time(legacy_schedule_input)

        install_days = _parse_install_days(install_days_input, "install_days")
        install_hour = _normalize_install_hour(install_hour_input, "install_hour")
        if not install_days:
            install_days = _parse_install_days(DEFAULT_OPTIONS["install_days"], "install_days")
        if not install_hour:
            install_hour = _normalize_install_hour(DEFAULT_OPTIONS["install_hour"], "install_hour")
        schedule_install_once_at = _normalize_schedule_once_at(merged["schedule_install_once_at"])
        schedule_install_frequency = _normalize_schedule_frequency(
            merged["schedule_install_frequency"],
            install_days=install_days,
            schedule_install_cron=str(merged["schedule_install_cron"] or ""),
            schedule_install_once_at=schedule_install_once_at,
        )
        schedule_install_monthday = _normalize_schedule_monthday(merged["schedule_install_monthday"])
        schedule_install_time_range_end = _infer_time_range_end(
            merged["schedule_install_time_range_end"],
            merged["maintenance_window"],
            install_hour,
        )

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

        if "schedule_allowed_weekdays" in user_options:
            allowed_weekdays = set(
                _parse_install_days(merged["schedule_allowed_weekdays"], "schedule_allowed_weekdays")
            )
        elif schedule_install_frequency == "weekly" and install_days:
            allowed_weekdays = set(install_days)
        else:
            allowed_weekdays = set(DEFAULT_WEEKDAYS)
        if not allowed_weekdays.issubset(VALID_WEEKDAYS):
            raise ConfigError("schedule_allowed_weekdays contains unsupported values")

        merged["install_days"] = ",".join(install_days) if install_days else ""
        merged["install_hour"] = install_hour
        merged["schedule_install_frequency"] = schedule_install_frequency
        merged["schedule_install_monthday"] = schedule_install_monthday
        merged["schedule_install_once_at"] = schedule_install_once_at
        merged["schedule_install_time_range_end"] = schedule_install_time_range_end
        merged["schedule_allowed_weekdays"] = list(allowed_weekdays)
        merged["schedule_install_weekday_time"] = (
            f"{install_days[0]}@{install_hour}" if len(install_days) == 1 and install_hour else ""
        )

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
            check_interval_minutes=int(merged["check_interval_minutes"]),
            install_days=install_days or tuple(DEFAULT_WEEKDAYS),
            install_hour=install_hour or DEFAULT_OPTIONS["install_hour"],
            schedule_install_frequency=schedule_install_frequency,
            schedule_install_monthday=schedule_install_monthday,
            schedule_install_once_at=schedule_install_once_at,
            schedule_install_time_range_end=schedule_install_time_range_end,
            auto_install=bool(merged["auto_install"]),
            create_backup=bool(merged["create_backup"]),
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
            backup_mode=backup_mode,
            backup_password=str(merged["backup_password"] or ""),
            backup_retention=int(merged["backup_retention"]),
            backup_partial_addons=list(merged["backup_partial_addons"]),
            rollback_on_failure=bool(merged["rollback_on_failure"]),
            schedule_check_interval_minutes=int(
                user_options.get("schedule_check_interval_minutes", merged["check_interval_minutes"])
            ),
            schedule_install_interval_minutes=int(
                user_options.get("schedule_install_interval_minutes", merged["check_interval_minutes"])
            ),
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
            "check_interval_minutes",
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
        if self.check_interval_minutes <= 0:
            raise ConfigError("check_interval_minutes must be > 0")
        if self.install_days and not self.install_hour:
            raise ConfigError("install_hour must be set when install_days are configured")
        if self.schedule_install_frequency not in VALID_SCHEDULE_FREQUENCIES:
            raise ConfigError(f"Unsupported schedule_install_frequency: {self.schedule_install_frequency}")
        if self.schedule_install_frequency == "weekly" and not self.install_days:
            raise ConfigError("install_days must be set for weekly schedules")
        if self.schedule_install_frequency == "monthly" and not 1 <= self.schedule_install_monthday <= 31:
            raise ConfigError("schedule_install_monthday must be between 1 and 31")
        if self.schedule_install_frequency == "once" and not self.schedule_install_once_at:
            raise ConfigError("schedule_install_once_at must be set for one-time schedules")
        if self.schedule_install_once_at:
            parse_iso_datetime(self.schedule_install_once_at)
        if self.schedule_install_time_range_end:
            _normalize_install_hour(self.schedule_install_time_range_end, "schedule_install_time_range_end")
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
    override_path = data_dir / OVERRIDE_OPTIONS_FILE.name
    payload: dict[str, Any] = {}
    if options_path.exists():
        payload.update(json.loads(options_path.read_text(encoding="utf-8")))
    if override_path.exists():
        payload.update(json.loads(override_path.read_text(encoding="utf-8")))
    return AppConfig.from_dict(payload, data_dir=data_dir)
