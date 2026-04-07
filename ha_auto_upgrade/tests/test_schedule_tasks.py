from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path

import pytest

from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.scheduler.engine import SchedulerEngine
from ha_autoupgrade.service import AutoUpgradeService
from ha_autoupgrade.storage.state import StateStore


def _build_service(tmp_path: Path) -> AutoUpgradeService:
    service = AutoUpgradeService.__new__(AutoUpgradeService)
    service.config = AppConfig.from_dict({"schedule_jitter_seconds": 0}, data_dir=tmp_path)
    service.scheduler = SchedulerEngine(service.config)
    service.state_store = StateStore(tmp_path / "state.json")
    service.logger = logging.getLogger("ha_autoupgrade.test.schedule_tasks")
    service._audit = lambda event, payload: None
    return service


def test_schedule_tasks_can_be_created_and_listed(tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    check_task = service.create_schedule_task(
        {
            "task_type": "auto_check_update",
            "weekdays": ["mon", "wed", "fri"],
            "hour": 4,
            "minute": 5,
            "enabled": True,
        }
    )
    update_task = service.create_schedule_task(
        {
            "task_type": "auto_update",
            "weekdays": ["mon", "wed", "fri"],
            "hour": 5,
            "minute": 0,
            "enabled": True,
        }
    )

    listed = service.list_schedule_tasks()

    assert {item["task_type"] for item in listed} == {"auto_check_update", "auto_update"}
    assert check_task["next_run"] is not None
    assert update_task["next_run"] is not None
    state = service.state_store.read()
    assert state["next_check"] is not None
    assert state["next_install"] is not None


def test_auto_update_requires_enabled_auto_check_update(tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    with pytest.raises(ValueError, match="Auto Update"):
        service.create_schedule_task(
            {
                "task_type": "auto_update",
                "weekdays": ["mon"],
                "hour": 3,
                "minute": 0,
                "enabled": True,
            }
        )


def test_disabling_auto_check_is_blocked_when_auto_update_enabled(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    check_task = service.create_schedule_task(
        {
            "task_type": "auto_check_update",
            "weekdays": ["mon"],
            "hour": 2,
            "minute": 0,
            "enabled": True,
        }
    )
    service.create_schedule_task(
        {
            "task_type": "auto_update",
            "weekdays": ["mon"],
            "hour": 3,
            "minute": 0,
            "enabled": True,
        }
    )

    with pytest.raises(ValueError, match="Auto Update"):
        service.set_schedule_task_enabled(check_task["id"], False)


def test_due_schedule_task_is_selected_from_state(tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    check_task = service.create_schedule_task(
        {
            "task_type": "auto_check_update",
            "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "hour": 1,
            "minute": 0,
            "enabled": True,
        }
    )

    state = service.state_store.read()
    for task in state["scheduled_tasks"]:
        if task["id"] == check_task["id"]:
            task["next_run"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    service._persist_schedule_tasks(state["scheduled_tasks"])

    due = service._select_due_schedule_task(service.state_store.read())

    assert due is not None
    assert due["id"] == check_task["id"]
