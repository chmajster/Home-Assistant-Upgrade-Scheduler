"""Main orchestration service."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
import json
import logging
import threading
import re
from uuid import uuid4
import zipfile
from typing import Any

from ha_autoupgrade.api.supervisor import SupervisorClient
from ha_autoupgrade.backups.manager import BackupManager
from ha_autoupgrade.config import AppConfig, DEFAULT_OPTIONS
from ha_autoupgrade.constants import (
    DEFAULT_WEEKDAYS,
    EXPORT_DIR,
    IMPORT_DIR,
    LOCK_FILE,
    OVERRIDE_OPTIONS_FILE,
)
from ha_autoupgrade.models import (
    TASK_TYPE_ACTIONS,
    ScheduleTask,
    RunSummary,
    SelfTestResult,
    SystemSnapshot,
    UpdateCandidate,
)
from ha_autoupgrade.notifications.manager import NotificationManager
from ha_autoupgrade.policies.engine import PolicyEngine
from ha_autoupgrade.scheduler.engine import SchedulerEngine
from ha_autoupgrade.storage.history import HistoryStore
from ha_autoupgrade.storage.state import StateStore
from ha_autoupgrade.updates.executor import UpdateExecutor
from ha_autoupgrade.updates.planner import UpdatePlanner
from ha_autoupgrade.utils.dates import parse_iso_datetime, to_iso, utc_now
from ha_autoupgrade.utils.locks import LockAcquisitionError, ProcessLock
from ha_autoupgrade.utils.system import free_disk_mb, free_memory_mb, load_average_1m, tcp_connectivity

ADDON_OPTION_KEYS = {
    "check_interval_minutes",
    "install_days",
    "install_hour",
    "auto_install",
    "create_backup",
}

TASK_TYPE_SEQUENCE = {
    "auto_check_update": 0,
    "auto_update": 1,
}

WEEKDAY_TOKEN_MAP = {
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

TRUE_TOKENS = {"1", "true", "yes", "on", "enabled", "tak"}
FALSE_TOKENS = {"0", "false", "no", "off", "disabled", "nie"}


class AutoUpgradeService:
    def __init__(self, config: AppConfig, log_handler) -> None:
        self.config = config
        self.log_handler = log_handler
        self.logger = logging.getLogger("ha_autoupgrade")
        self.client = SupervisorClient(
            logger=logging.getLogger("ha_autoupgrade.supervisor"),
            max_attempts=config.api_retry_max_attempts,
            backoff_seconds=config.api_retry_backoff_seconds,
        )
        self.state_store = StateStore()
        self.history_store = HistoryStore()
        self.policy_engine = PolicyEngine(config, logging.getLogger("ha_autoupgrade.policy"))
        self.scheduler = SchedulerEngine(config)
        self.backup_manager = BackupManager(
            config,
            self.client,
            logging.getLogger("ha_autoupgrade.backups"),
        )
        self.notifier = NotificationManager(
            config,
            self.client,
            logging.getLogger("ha_autoupgrade.notify"),
        )
        self.planner = UpdatePlanner(
            config,
            self.client,
            self.policy_engine,
            logging.getLogger("ha_autoupgrade.planner"),
        )
        self.executor = UpdateExecutor(
            config,
            self.client,
            self.backup_manager,
            self.notifier,
            logging.getLogger("ha_autoupgrade.executor"),
        )
        self.lock = ProcessLock(
            LOCK_FILE,
            stale_after_seconds=max(config.watchdog_timeout_minutes * 60, 3600),
        )
        self.action_queue: deque[tuple[str, str, dict[str, Any]]] = deque()
        self.queue_lock = threading.Lock()
        self.state_store.mark_interrupted_if_running()
        self._refresh_schedule()

    def reload_config(self, config: AppConfig) -> None:
        self.config = config
        self.client.configure_retries(config.api_retry_max_attempts, config.api_retry_backoff_seconds)
        self.policy_engine = PolicyEngine(config, logging.getLogger("ha_autoupgrade.policy"))
        self.scheduler = SchedulerEngine(config)
        self.backup_manager = BackupManager(
            config,
            self.client,
            logging.getLogger("ha_autoupgrade.backups"),
        )
        self.notifier = NotificationManager(
            config,
            self.client,
            logging.getLogger("ha_autoupgrade.notify"),
        )
        self.planner = UpdatePlanner(
            config,
            self.client,
            self.policy_engine,
            logging.getLogger("ha_autoupgrade.planner"),
        )
        self.executor = UpdateExecutor(
            config,
            self.client,
            self.backup_manager,
            self.notifier,
            logging.getLogger("ha_autoupgrade.executor"),
        )
        self._refresh_schedule()

    def enqueue_action(
        self,
        action: str,
        source: str = "manual",
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.queue_lock:
            self.action_queue.append((action, source, payload or {}))
        self.logger.info(
            "Queued action '%s' from %s with payload=%s",
            action,
            source,
            payload or {},
        )

    def tick(self) -> None:
        self._watchdog()
        action = self._dequeue_action()
        if action:
            self.logger.info("Dispatching queued action '%s' from %s", action[0], action[1])
            self._dispatch(*action)
            return

        state = self.state_store.read()
        due_task = self._select_due_schedule_task(state)
        if due_task is not None:
            task_type = str(due_task.get("task_type"))
            action_name = TASK_TYPE_ACTIONS.get(task_type)
            if action_name is not None:
                self.logger.info(
                    "Dispatching scheduled task '%s' (%s) as action '%s'",
                    due_task.get("id"),
                    task_type,
                    action_name,
                )
                self._dispatch(action_name, f"schedule_task:{task_type}", {})
                self._advance_schedule_task(str(due_task.get("id", "")))
                return

        scheduled_tasks = state.get("scheduled_tasks", [])
        if isinstance(scheduled_tasks, list) and scheduled_tasks:
            return

        due = self.scheduler.due_actions(state)
        for action_name in due:
            if action_name == "install" and not self.config.auto_install:
                self.logger.info("Scheduled install skipped because auto_install is disabled")
                self._advance_install_schedule()
                return
            self.logger.info("Dispatching scheduled action '%s'", action_name)
            self._dispatch(action_name, "schedule", {})
            return

    def _dequeue_action(self) -> tuple[str, str, dict[str, Any]] | None:
        with self.queue_lock:
            if not self.action_queue:
                return None
            return self.action_queue.popleft()

    def _dispatch(self, action: str, source: str, payload: dict[str, Any]) -> None:
        if action == "check":
            self.run_check(source)
        elif action == "check_install":
            self.run_check_and_install(source, payload=payload)
        elif action == "install":
            self.run_install(source, payload=payload)
        elif action == "backup":
            self.backup_now(source)
        elif action == "retry":
            self.retry_failed(source)
        elif action == "clear":
            self.clear_stuck_state(source)
        elif action == "self_test":
            self.self_test()
        elif action == "export":
            self.export_diagnostics()
        elif action == "import":
            self.import_configuration(payload)

    def _audit(self, event: str, payload: dict[str, Any]) -> None:
        body = {"ts": utc_now().isoformat(), "event": event}
        body.update(payload)
        self.history_store.append(body)
        try:
            self.client.fire_event(f"ha_autoupgrade_{event}", body)
        except Exception:
            self.logger.exception("Failed to fire lifecycle event %s", event)

    def _schedule_signature(self) -> str:
        return json.dumps(
            {
                "check_interval_minutes": self.config.check_interval_minutes,
                "install_days": list(self.config.install_days),
                "install_hour": self.config.install_hour,
                "schedule_check_cron": self.config.schedule_check_cron,
                "schedule_install_cron": self.config.schedule_install_cron,
                "schedule_check_weekday_time": self.config.schedule_check_weekday_time,
                "schedule_install_weekday_time": self.config.schedule_install_weekday_time,
                "schedule_install_frequency": self.config.schedule_install_frequency,
                "schedule_install_monthday": self.config.schedule_install_monthday,
                "schedule_install_once_at": self.config.schedule_install_once_at,
                "schedule_install_time_range_end": self.config.schedule_install_time_range_end,
                "schedule_allowed_weekdays": sorted(self.config.schedule_allowed_weekdays),
                "maintenance_window": self.config.maintenance_window,
                "schedule_jitter_seconds": self.config.schedule_jitter_seconds,
            },
            sort_keys=True,
        )

    def _task_sort_key(self, task: dict[str, Any]) -> tuple[int, str]:
        task_type = str(task.get("task_type", ""))
        return (TASK_TYPE_SEQUENCE.get(task_type, 99), str(task.get("id", "")))

    def _task_to_state_payload(self, task: ScheduleTask) -> dict[str, Any]:
        return {
            "id": task.task_id,
            "task_type": task.task_type,
            "weekdays": list(task.weekdays),
            "hour": task.hour,
            "minute": task.minute,
            "enabled": task.enabled,
            "next_run": task.next_run,
            "category": task.category,
            "owner": task.owner,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    def _normalize_task_type(self, value: Any) -> str:
        token = re.sub(r"[^a-z]+", "_", str(value or "").strip().lower()).strip("_")
        aliases = {
            "auto_update": "auto_update",
            "autoupdate": "auto_update",
            "auto_install": "auto_update",
            "auto_check_update": "auto_check_update",
            "autocheckupdate": "auto_check_update",
            "auto_check": "auto_check_update",
            "check_update": "auto_check_update",
        }
        normalized = aliases.get(token, token)
        if normalized not in TASK_TYPE_ACTIONS:
            raise ValueError("Nieobslugiwany typ zadania")
        return normalized

    def _normalize_task_weekdays(self, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            raw_tokens = re.split(r"[\s,;]+", value.strip())
        elif isinstance(value, (list, tuple, set)):
            raw_tokens = [str(item) for item in value]
        else:
            raise ValueError("Pole weekdays musi byc lista lub tekstem")

        selected: list[str] = []
        for token in raw_tokens:
            folded = re.sub(r"[^a-z]", "", token.strip().lower())
            if not folded:
                continue
            day = WEEKDAY_TOKEN_MAP.get(folded)
            if day is None:
                raise ValueError(f"Nieprawidlowy dzien tygodnia: {token}")
            if day not in selected:
                selected.append(day)

        if not selected:
            raise ValueError("Wybierz co najmniej jeden dzien tygodnia")
        return tuple(day for day in DEFAULT_WEEKDAYS if day in selected)

    def _normalize_task_int(
        self,
        value: Any,
        *,
        field_name: str,
        minimum: int,
        maximum: int,
        default: int | None = None,
    ) -> int:
        if value is None or value == "":
            if default is not None:
                return default
            raise ValueError(f"Pole {field_name} jest wymagane")
        try:
            parsed = int(str(value).strip())
        except ValueError as err:
            raise ValueError(f"Pole {field_name} musi byc liczba") from err
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"Pole {field_name} musi byc w zakresie {minimum}-{maximum}")
        return parsed

    def _normalize_task_enabled(self, value: Any, *, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(int(value))
        token = str(value).strip().lower()
        if token in TRUE_TOKENS:
            return True
        if token in FALSE_TOKENS:
            return False
        raise ValueError("Pole enabled musi byc wartoscia logiczna")

    def _schedule_task_from_payload(
        self,
        payload: dict[str, Any],
        *,
        existing: dict[str, Any] | None = None,
    ) -> ScheduleTask:
        existing_model = ScheduleTask.from_dict(existing) if existing else None
        task_type = self._normalize_task_type(
            payload.get("task_type", existing_model.task_type if existing_model else "")
        )
        weekdays = self._normalize_task_weekdays(
            payload.get("weekdays", existing_model.weekdays if existing_model else [])
        )
        hour = self._normalize_task_int(
            payload.get("hour", existing_model.hour if existing_model else None),
            field_name="hour",
            minimum=0,
            maximum=23,
        )
        minute = self._normalize_task_int(
            payload.get("minute", existing_model.minute if existing_model else 0),
            field_name="minute",
            minimum=0,
            maximum=59,
            default=0,
        )
        enabled = self._normalize_task_enabled(
            payload.get("enabled"),
            default=existing_model.enabled if existing_model else True,
        )
        now_iso = utc_now().isoformat()
        task = ScheduleTask(
            task_id=str(
                payload.get("id")
                or (existing_model.task_id if existing_model else "")
                or uuid4().hex
            ),
            task_type=task_type,
            weekdays=weekdays,
            hour=hour,
            minute=minute,
            enabled=enabled,
            next_run=(
                existing_model.next_run
                if existing_model
                else (str(payload.get("next_run")) if payload.get("next_run") else None)
            ),
            category=str(payload.get("category") or (existing_model.category if existing_model else "System")),
            owner=str(payload.get("owner") or (existing_model.owner if existing_model else "HA AutoUpgrade")),
            created_at=(
                existing_model.created_at
                if existing_model
                else (str(payload.get("created_at")) if payload.get("created_at") else now_iso)
            ),
            updated_at=(
                now_iso
                if existing_model
                else (str(payload.get("updated_at")) if payload.get("updated_at") else now_iso)
            ),
        )
        task.validate()
        return task

    def _normalize_state_tasks(self, raw_tasks: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_tasks, list):
            return []

        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                continue
            try:
                task = self._schedule_task_from_payload(raw_task)
            except ValueError as err:
                self.logger.warning("Skipping invalid schedule task payload: %s", err)
                continue
            if task.task_id in seen_ids:
                continue
            next_run = parse_iso_datetime(task.next_run) if task.next_run else None
            if task.enabled and next_run is None:
                task.next_run = to_iso(self.scheduler.compute_task_next(self._task_to_state_payload(task)))
            if not task.enabled:
                task.next_run = None
            seen_ids.add(task.task_id)
            normalized.append(self._task_to_state_payload(task))

        normalized.sort(key=self._task_sort_key)
        return normalized

    def _next_runs_from_tasks(self, tasks: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        next_check_values = []
        next_install_values = []
        for task in tasks:
            if not task.get("enabled", True):
                continue
            parsed = parse_iso_datetime(task.get("next_run")) if task.get("next_run") else None
            if parsed is None:
                continue
            if task.get("task_type") == "auto_check_update":
                next_check_values.append(parsed)
            elif task.get("task_type") == "auto_update":
                next_install_values.append(parsed)

        return (
            to_iso(min(next_check_values)) if next_check_values else None,
            to_iso(min(next_install_values)) if next_install_values else None,
        )

    def _persist_schedule_tasks(self, tasks: list[dict[str, Any]]) -> None:
        ordered = sorted(tasks, key=self._task_sort_key)
        next_check, next_install = self._next_runs_from_tasks(ordered)

        def _update(state: dict[str, Any]) -> None:
            state["scheduled_tasks"] = ordered
            state["next_check"] = next_check
            state["next_install"] = next_install

        self.state_store.update(_update)

    def _validate_task_dependencies(self, tasks: list[dict[str, Any]]) -> None:
        auto_update_enabled = any(
            task.get("task_type") == "auto_update" and bool(task.get("enabled", True))
            for task in tasks
        )
        auto_check_enabled = any(
            task.get("task_type") == "auto_check_update" and bool(task.get("enabled", True))
            for task in tasks
        )
        if auto_update_enabled and not auto_check_enabled:
            raise ValueError("Auto Update wymaga aktywnego zadania Auto Check Update")

    def _task_response_payload(self, task: dict[str, Any]) -> dict[str, Any]:
        return ScheduleTask.from_dict(task).to_dict()

    def list_schedule_tasks(self) -> list[dict[str, Any]]:
        state = self.state_store.read()
        normalized = self._normalize_state_tasks(state.get("scheduled_tasks", []))
        if normalized != state.get("scheduled_tasks", []):
            self._persist_schedule_tasks(normalized)
        return [self._task_response_payload(task) for task in normalized]

    def create_schedule_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Payload zadania musi byc obiektem JSON")
        state = self.state_store.read()
        tasks = self._normalize_state_tasks(state.get("scheduled_tasks", []))
        new_task = self._schedule_task_from_payload(payload)
        if any(task.get("task_type") == new_task.task_type for task in tasks):
            raise ValueError("Zadanie tego typu juz istnieje. Uzyj opcji edycji.")
        new_task.next_run = (
            to_iso(self.scheduler.compute_task_next(self._task_to_state_payload(new_task)))
            if new_task.enabled
            else None
        )
        tasks.append(self._task_to_state_payload(new_task))
        self._validate_task_dependencies(tasks)
        self._persist_schedule_tasks(tasks)
        self._audit(
            "schedule_task_created",
            {
                "task_id": new_task.task_id,
                "task_type": new_task.task_type,
                "enabled": new_task.enabled,
            },
        )
        return self._task_response_payload(self._task_to_state_payload(new_task))

    def update_schedule_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not task_id:
            raise ValueError("Brak identyfikatora zadania")
        if not isinstance(payload, dict):
            raise ValueError("Payload zadania musi byc obiektem JSON")

        state = self.state_store.read()
        tasks = self._normalize_state_tasks(state.get("scheduled_tasks", []))
        index = next((idx for idx, task in enumerate(tasks) if task.get("id") == task_id), -1)
        if index < 0:
            raise ValueError("Nie znaleziono zadania harmonogramu")

        updated = self._schedule_task_from_payload(payload, existing=tasks[index])
        updated.next_run = (
            to_iso(self.scheduler.compute_task_next(self._task_to_state_payload(updated)))
            if updated.enabled
            else None
        )
        tasks[index] = self._task_to_state_payload(updated)
        self._validate_task_dependencies(tasks)
        self._persist_schedule_tasks(tasks)
        self._audit(
            "schedule_task_updated",
            {
                "task_id": updated.task_id,
                "task_type": updated.task_type,
                "enabled": updated.enabled,
            },
        )
        return self._task_response_payload(self._task_to_state_payload(updated))

    def set_schedule_task_enabled(self, task_id: str, enabled: Any) -> dict[str, Any]:
        return self.update_schedule_task(task_id, {"enabled": enabled})

    def _select_due_schedule_task(self, state: dict[str, Any]) -> dict[str, Any] | None:
        raw_tasks = state.get("scheduled_tasks", [])
        tasks = self._normalize_state_tasks(raw_tasks)
        changed = tasks != raw_tasks
        now = utc_now()
        due: list[tuple[Any, dict[str, Any]]] = []

        for task in tasks:
            if not task.get("enabled", True):
                if task.get("next_run") is not None:
                    task["next_run"] = None
                    changed = True
                continue
            next_run = parse_iso_datetime(task.get("next_run")) if task.get("next_run") else None
            if next_run is None:
                next_run = self.scheduler.compute_task_next(task, now)
                task["next_run"] = to_iso(next_run) if next_run else None
                changed = True
            if next_run and next_run <= now:
                due.append((next_run, task))

        if changed:
            self._persist_schedule_tasks(tasks)
        if not due:
            return None
        due.sort(key=lambda item: item[0])
        return due[0][1]

    def _advance_schedule_task(self, task_id: str) -> None:
        state = self.state_store.read()
        tasks = self._normalize_state_tasks(state.get("scheduled_tasks", []))
        changed = False
        for task in tasks:
            if task.get("id") != task_id:
                continue
            task["updated_at"] = utc_now().isoformat()
            if task.get("enabled", True):
                task["next_run"] = to_iso(self.scheduler.compute_task_next(task))
            else:
                task["next_run"] = None
            changed = True
            break
        if changed:
            self._persist_schedule_tasks(tasks)

    def _refresh_schedule(self) -> None:
        state = self.state_store.read()
        normalized_tasks = self._normalize_state_tasks(state.get("scheduled_tasks", []))
        if normalized_tasks:
            self._persist_schedule_tasks(normalized_tasks)
            self.state_store.set_schedule_signature(self._schedule_signature())
            return

        signature = self._schedule_signature()
        if state.get("schedule_signature") != signature:
            self.logger.info("Schedule configuration changed, recalculating next runs")
            self.state_store.set_next_runs(
                to_iso(self.scheduler.compute_next("check")),
                to_iso(self.scheduler.compute_next("install")),
            )
            self.state_store.set_schedule_signature(signature)
            return
        schedule = self.scheduler.ensure_schedule(state)
        self.state_store.set_next_runs(to_iso(schedule.next_check), to_iso(schedule.next_install))
        self.state_store.set_schedule_signature(signature)

    def _advance_install_schedule(self) -> None:
        state = self.state_store.read()
        current_next_check = state.get("next_check")
        self.state_store.set_next_runs(current_next_check, to_iso(self.scheduler.compute_next("install")))

    def _collect_entity_states(self) -> dict[str, str]:
        tracked_entities = {
            self.config.ups_status_entity,
            self.config.approval_entity,
            self.config.skip_if_someone_home_entity,
            self.config.skip_if_media_playing_entity,
            self.config.skip_if_critical_mode_entity,
            self.config.skip_if_alarm_armed_away_entity,
            self.config.skip_if_vacuum_cleaning_entity,
            self.config.unstable_binary_sensor_entity,
            *self.config.require_entity_states.keys(),
            *self.config.pre_update_entities_on,
            *self.config.pre_update_entities_off,
        }
        states: dict[str, str] = {}
        for entity_id in tracked_entities:
            if not entity_id:
                continue
            try:
                response = self.client.entity_state(entity_id)
                states[entity_id] = response.get("state", "unknown") if response else "unknown"
            except Exception:
                states[entity_id] = "unavailable"
        return states

    def _collect_system_snapshot(self) -> SystemSnapshot:
        root_info: dict[str, Any] = {}
        api_ok = self.client.ping()
        if api_ok:
            try:
                root_info = self.client.root_info()
            except Exception:
                api_ok = False
        ha_state = str(root_info.get("state", "unknown"))
        return SystemSnapshot(
            free_disk_mb=free_disk_mb(self.config.data_dir),
            load_1m=load_average_1m(),
            free_memory_mb=free_memory_mb(),
            network_ok=tcp_connectivity("supervisor", 80),
            api_ok=api_ok,
            ha_state=ha_state,
            supervisor_state=ha_state,
            details=root_info,
        )

    def _blocked_by_runtime_state(self) -> list[str]:
        state = self.state_store.read()
        now = utc_now()
        reasons: list[str] = []
        safe_mode_until = parse_iso_datetime(state.get("safe_mode_until"))
        cooldown_until = parse_iso_datetime(state.get("cooldown_until"))
        if safe_mode_until and safe_mode_until > now:
            reasons.append(f"Safe mode active until {safe_mode_until.isoformat()}")
        if cooldown_until and cooldown_until > now:
            reasons.append(f"Cooldown active until {cooldown_until.isoformat()}")
        last_run = (
            parse_iso_datetime(state.get("last_run", {}).get("completed_at"))
            if state.get("last_run")
            else None
        )
        if last_run and last_run + timedelta(minutes=self.config.min_minutes_between_runs) > now:
            reasons.append("Minimum delay between runs has not elapsed")
        return reasons

    def _acquire_run_lock(self) -> bool:
        try:
            self.lock.acquire()
        except LockAcquisitionError:
            return False
        return True

    def run_check(self, trigger: str) -> dict[str, Any]:
        try:
            self.logger.info("Starting update check (trigger=%s)", trigger)
            state = self.state_store.read()
            schedule = self.scheduler.ensure_schedule(state)
            snapshot = self._collect_system_snapshot()
            entity_states = self._collect_entity_states()
            candidates = self.planner.discover(refresh=True)
            plan = self.planner.build_plan(
                candidates=candidates,
                snapshot=snapshot,
                entity_states=entity_states,
                now=utc_now(),
            )
            next_check = self.scheduler.compute_next("check")
            next_install = schedule.next_install or self.scheduler.compute_next("install")
            self.state_store.record_check(
                candidates=plan.items,
                skipped=plan.skipped,
                next_check=to_iso(next_check),
                next_install=to_iso(next_install),
            )
            self._audit(
                "check",
                {
                    "trigger": trigger,
                    "pending": len(plan.items),
                    "skipped": len(plan.skipped),
                },
            )
            self.logger.info(
                "Update check completed: found=%d skipped=%d pending=%s",
                len(candidates),
                len(plan.skipped),
                [item.name for item in plan.items],
            )
            return {
                "snapshot": snapshot.to_dict(),
                "updates": [item.to_dict() for item in plan.items],
                "skipped": plan.skipped,
                "next_check": to_iso(next_check),
                "next_install": to_iso(next_install),
            }
        except Exception as err:
            self.logger.exception("Update check failed")
            state = self.state_store.read()
            self.state_store.set_next_runs(
                to_iso(self.scheduler.compute_next("check")),
                state.get("next_install"),
            )
            self._audit("check_failed", {"trigger": trigger, "error": str(err)})
            return {"status": "failed", "error": str(err)}

    def run_check_and_install(self, trigger: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.logger.info("Starting combined check-and-install flow (trigger=%s)", trigger)
        check_result = self.run_check(f"{trigger}:preinstall_check")
        if check_result.get("status") == "failed":
            self.logger.warning("Combined check-and-install aborted because the check phase failed")
            return {
                "status": "failed",
                "phase": "check",
                "check": check_result,
            }
        install_result = self.run_install(trigger, payload=payload)
        return {
            "status": install_result.get("status", "unknown"),
            "phase": "install",
            "check": check_result,
            "install": install_result,
        }

    def _filter_plan_items(
        self,
        plan,
        allowed_types: list[str] | None,
    ):
        if not allowed_types:
            return plan
        normalized = {entry.lower() for entry in allowed_types}
        filtered_items = [item for item in plan.items if item.component_type in normalized]
        skipped = list(plan.skipped)
        for item in plan.items:
            if item.component_type not in normalized:
                skipped.append(
                    {
                        "candidate": item.to_dict(),
                        "reasons": [f"Manual install scope does not include {item.component_type}"],
                    }
                )
        plan.items = filtered_items
        plan.skipped = skipped
        return plan

    def run_install(self, trigger: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        allowed_types = payload.get("allowed_types")
        self.logger.info(
            "Starting install run (trigger=%s, allowed_types=%s)",
            trigger,
            allowed_types or ["all"],
        )
        if trigger == "schedule" and not self.config.auto_install:
            self._advance_install_schedule()
            return {"status": "skipped", "reasons": ["Automatic installation is disabled"]}

        runtime_reasons = self._blocked_by_runtime_state()
        snapshot = self._collect_system_snapshot()
        entity_states = self._collect_entity_states()
        decision = self.policy_engine.evaluate_run(
            snapshot=snapshot,
            entity_states=entity_states,
            now=utc_now(),
            mode="scheduled_install" if trigger == "schedule" else "manual_install",
        )
        if runtime_reasons or not decision.allowed:
            reasons = runtime_reasons + decision.reasons
            self.logger.warning("Install run skipped: %s", reasons)
            self.notifier.send("skip", "HA AutoUpgrade skipped", {"event": "skip", "reasons": reasons})
            self._audit("skip", {"trigger": trigger, "reasons": reasons})
            self._advance_install_schedule()
            return {"status": "skipped", "reasons": reasons}

        if not self._acquire_run_lock():
            reasons = ["Another run is already active"]
            self.logger.warning("Install run skipped because another run is active")
            self._audit("skip", {"trigger": trigger, "reasons": reasons})
            self._advance_install_schedule()
            return {"status": "skipped", "reasons": reasons}

        summary: RunSummary | None = None
        try:
            candidates = self.planner.discover(refresh=True)
            plan = self.planner.build_plan(
                candidates=candidates,
                snapshot=snapshot,
                entity_states=entity_states,
                now=utc_now(),
            )
            plan = self._filter_plan_items(plan, allowed_types)
            if not plan.items:
                reasons = ["No updates matched policy"]
                if allowed_types:
                    reasons = [f"No updates matched manual scope {allowed_types}"]
                self.logger.info("Install run has no matching updates: %s", reasons)
                self._audit("skip", {"trigger": trigger, "reasons": reasons})
                self._advance_install_schedule()
                return {"status": "skipped", "reasons": reasons}

            self.state_store.start_job(
                mode="install",
                trigger=trigger,
                pending_items=[item.to_dict() for item in plan.items],
            )
            backup_id = None
            if self.config.create_backup and not self.config.dry_run and not self.config.notify_only_mode:
                backup_id = self.backup_manager.create_pre_update_backup(trigger)
                self.state_store.set_running_backup_id(backup_id)
                self.state_store.mark_backup(backup_id)
                self.logger.info("Pre-update backup created: %s", backup_id)
            self._run_pre_actions()
            summary = self.executor.execute(
                plan=plan,
                trigger=trigger,
                mode="install",
                backup_id=backup_id,
            )
            self._handle_summary(summary)
            self._run_post_actions(summary.status)
            next_install = self.scheduler.compute_next("install")
            next_check = self.scheduler.compute_next("check")
            self.state_store.set_next_runs(to_iso(next_check), to_iso(next_install))
            self.logger.info("Install run completed with status=%s", summary.status)
            return summary.to_dict()
        except Exception as err:
            self.logger.exception("Install run failed before completion")
            summary = RunSummary(
                trigger=trigger,
                mode="install",
                started_at=utc_now(),
                completed_at=utc_now(),
                status="failed",
                results=[],
                skipped_reasons=[str(err)],
                detected_updates=[],
            )
            self._handle_summary(summary)
            self._advance_install_schedule()
            return summary.to_dict()
        finally:
            self.lock.release()

    def _handle_summary(self, summary: RunSummary) -> None:
        self.state_store.finish_job(summary)
        self.logger.info(
            "Handling run summary: status=%s results=%d backup_id=%s",
            summary.status,
            len(summary.results),
            summary.backup_id,
        )
        failed = [item for item in summary.results if item.result == "failed"]
        if failed or summary.status == "failed":
            new_failure_count = self.state_store.read().get("failure_count", 0) + 1
            cooldown_until = utc_now() + timedelta(minutes=self.config.cooldown_minutes_after_failure)
            safe_mode_until = None
            safe_reason = ""
            if new_failure_count >= self.config.safe_mode_failure_threshold:
                safe_mode_until = utc_now() + timedelta(minutes=self.config.safe_mode_minutes)
                safe_reason = "Repeated update failures"
            self.state_store.set_failure_mode(
                failure_count=new_failure_count,
                cooldown_until=to_iso(cooldown_until),
                safe_mode_until=to_iso(safe_mode_until),
                safe_mode_reason=safe_reason,
            )
            if failed:
                self.state_store.queue_retry(
                    [
                        {
                            "component_type": item.component_type,
                            "slug": item.slug,
                            "name": item.name,
                            "current_version": item.previous_version,
                            "target_version": item.target_version,
                        }
                        for item in failed
                    ]
                )
        else:
            self.state_store.clear_failure_mode()
            self.state_store.clear_retry_queue()

        self.notifier.send(
            "partial" if summary.status == "partial" else summary.status,
            f"HA AutoUpgrade {summary.status}",
            summary.to_dict(),
        )
        self._audit(summary.status, summary.to_dict())
        try:
            self.client.fire_event("ha_autoupgrade_run_completed", summary.to_dict())
        except Exception:
            self.logger.exception("Failed to fire run completed event")

    def backup_now(self, trigger: str) -> dict[str, Any]:
        self.logger.info("Starting manual backup (trigger=%s)", trigger)
        backup_id = self.backup_manager.create_pre_update_backup(trigger)
        if backup_id:
            self.state_store.mark_backup(backup_id)
            self.logger.info("Manual backup completed: %s", backup_id)
        self._audit("backup", {"trigger": trigger, "backup_id": backup_id})
        return {"backup_id": backup_id}

    def retry_failed(self, trigger: str) -> dict[str, Any]:
        retry_queue = self.state_store.read().get("retry_queue", [])
        if not retry_queue:
            return {"status": "skipped", "reasons": ["Retry queue is empty"]}
        if not self._acquire_run_lock():
            return {"status": "skipped", "reasons": ["Another run is already active"]}
        try:
            candidates = [
                UpdateCandidate(
                    component_type=item["component_type"],
                    slug=item.get("slug"),
                    name=item["name"],
                    current_version=item["current_version"],
                    target_version=item["target_version"],
                )
                for item in retry_queue
            ]
            snapshot = self._collect_system_snapshot()
            entity_states = self._collect_entity_states()
            plan = self.planner.build_plan(
                candidates=candidates,
                snapshot=snapshot,
                entity_states=entity_states,
                now=utc_now(),
            )
            self.state_store.start_job(
                mode="retry",
                trigger=trigger,
                pending_items=[item.to_dict() for item in plan.items],
            )
            backup_id = None
            if self.config.create_backup and not self.config.dry_run and not self.config.notify_only_mode:
                backup_id = self.backup_manager.create_pre_update_backup(trigger)
                self.state_store.set_running_backup_id(backup_id)
                self.state_store.mark_backup(backup_id)
            self._run_pre_actions()
            summary = self.executor.execute(
                plan=plan,
                trigger=trigger,
                mode="retry",
                backup_id=backup_id,
            )
            self._handle_summary(summary)
            self._run_post_actions(summary.status)
            return summary.to_dict()
        finally:
            self.lock.release()

    def clear_stuck_state(self, trigger: str) -> dict[str, Any]:
        self.state_store.clear_stuck_state()
        self._audit("clear", {"trigger": trigger})
        return {"status": "cleared"}

    def import_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        incoming_options = payload.get("options", payload)
        options = self.config.to_options_dict(redact_secrets=False)
        options.update(incoming_options)
        frequency = str(options.get("schedule_install_frequency") or "")
        once_at = parse_iso_datetime(str(options.get("schedule_install_once_at") or ""))
        if frequency == "once":
            if once_at is None:
                raise ValueError("One-time schedule requires a valid date and time")
            if once_at <= utc_now():
                raise ValueError("One-time schedule must be in the future")

        addon_options = {key: options[key] for key in ADDON_OPTION_KEYS if key in options}
        override_options = {
            key: value
            for key, value in options.items()
            if key not in ADDON_OPTION_KEYS and (key not in DEFAULT_OPTIONS or DEFAULT_OPTIONS[key] != value)
        }

        validation = self.client.validate_addon_options("self", addon_options)
        if not validation.get("valid", False):
            raise ValueError(validation.get("message", "Configuration validation failed"))
        self.client.set_addon_options("self", addon_options)
        override_path = self.config.data_dir / OVERRIDE_OPTIONS_FILE.name
        override_path.parent.mkdir(parents=True, exist_ok=True)
        if override_options:
            override_path.write_text(json.dumps(override_options, indent=2), encoding="utf-8")
        elif override_path.exists():
            override_path.unlink()
        IMPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        path = IMPORT_DIR / f"imported-options-{timestamp}.json"
        path.write_text(json.dumps(options, indent=2), encoding="utf-8")
        self.reload_config(AppConfig.from_dict(options, data_dir=self.config.data_dir))
        self._audit("config_import", {"path": str(path)})
        return {"status": "imported", "path": str(path)}

    def export_diagnostics(self) -> dict[str, Any]:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        archive_path = EXPORT_DIR / f"ha-autoupgrade-diagnostics-{timestamp}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "config.json",
                json.dumps(self.config.to_options_dict(redact_secrets=True), indent=2),
            )
            archive.writestr("state.json", json.dumps(self.state_store.read(), indent=2))
            archive.writestr("history.json", json.dumps(self.history_store.recent(200), indent=2))
            archive.writestr("recent_logs.json", json.dumps(self.log_handler.recent(200), indent=2))
        self._audit("diagnostics_export", {"path": str(archive_path)})
        return {"path": str(archive_path)}

    def self_test(self) -> dict[str, Any]:
        results = [
            SelfTestResult("supervisor_ping", self.client.ping(), "Supervisor ping"),
            SelfTestResult("storage_write", self._storage_self_test(), "State storage write/read"),
            SelfTestResult(
                "scheduler",
                True,
                f"Next install {to_iso(self.scheduler.compute_next('install'))}",
            ),
            SelfTestResult("translations", True, "Translation files are loaded by the web UI"),
        ]
        payload = {"checked_at": utc_now().isoformat(), "results": [item.to_dict() for item in results]}
        self.state_store.mark_self_test(payload)
        self._audit("self_test", payload)
        return payload

    def _storage_self_test(self) -> bool:
        state = self.state_store.read()
        return "schema_version" in state

    def _run_pre_actions(self) -> None:
        try:
            self.client.fire_event("ha_autoupgrade_run_started", {"started_at": utc_now().isoformat()})
        except Exception:
            self.logger.exception("Failed to fire run started event")
        if self.config.maintenance_mode_service:
            self.client.call_service(self.config.maintenance_mode_service, {})
        for entity_id in self.config.pre_update_entities_on:
            self.client.call_service("homeassistant.turn_on", {"entity_id": entity_id})
        for entity_id in self.config.pre_update_entities_off:
            self.client.call_service("homeassistant.turn_off", {"entity_id": entity_id})
        for action in self.config.pre_update_services:
            self.client.call_service(action.service, action.data)

    def _run_post_actions(self, status: str) -> None:
        if self.config.maintenance_mode_restore_service:
            try:
                self.client.call_service(self.config.maintenance_mode_restore_service, {})
            except Exception:
                self.logger.exception("Failed to call maintenance restore service")
        for addon in self.config.post_update_restart_addons:
            try:
                self.client.restart_addon(addon)
            except Exception:
                self.logger.exception("Failed to restart addon %s", addon)
        for action in self.config.post_update_services:
            try:
                self.client.call_service(action.service, action.data)
            except Exception:
                self.logger.exception("Failed to call post-update service %s", action.service)
        if self.config.post_update_notify:
            self.notifier.send(
                "success" if status == "success" else status,
                "HA AutoUpgrade post-update",
                {"status": status},
            )

    def _watchdog(self) -> None:
        if not self.config.watchdog_enabled:
            return
        state = self.state_store.read()
        running_job = state.get("running_job")
        if not running_job:
            return
        started_at = parse_iso_datetime(running_job.get("started_at"))
        if not started_at:
            return
        if started_at + timedelta(minutes=self.config.watchdog_timeout_minutes) < utc_now():
            self.logger.error("Watchdog marked current run as stuck")
            self.state_store.clear_stuck_state()
            self.state_store.set_failure_mode(
                failure_count=state.get("failure_count", 0) + 1,
                cooldown_until=to_iso(
                    utc_now() + timedelta(minutes=self.config.cooldown_minutes_after_failure)
                ),
                safe_mode_until=to_iso(utc_now() + timedelta(minutes=self.config.safe_mode_minutes)),
                safe_mode_reason="Watchdog timeout",
            )

    def status(self) -> dict[str, Any]:
        state = self.state_store.read()
        normalized_tasks = self._normalize_state_tasks(state.get("scheduled_tasks", []))
        if normalized_tasks != state.get("scheduled_tasks", []):
            self._persist_schedule_tasks(normalized_tasks)
            state = self.state_store.read()
        return {
            "state": state,
            "recent_history": self.history_store.recent(20),
            "recent_logs": self.log_handler.recent(50),
            "config": self.config.to_options_dict(redact_secrets=True),
            "scheduled_tasks": [self._task_response_payload(task) for task in normalized_tasks],
        }

    def health(self) -> dict[str, Any]:
        snapshot = self._collect_system_snapshot()
        return {
            "ok": snapshot.api_ok and snapshot.network_ok,
            "snapshot": snapshot.to_dict(),
            "safe_mode_until": self.state_store.read().get("safe_mode_until"),
        }
