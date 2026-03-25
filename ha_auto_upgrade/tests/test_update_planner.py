from __future__ import annotations

from datetime import UTC, datetime
import logging

from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.models import SystemSnapshot
from ha_autoupgrade.policies.engine import PolicyEngine
from ha_autoupgrade.updates.planner import UpdatePlanner


class PlannerClientStub:
    def reload_updates(self):
        return None

    def reload_store(self):
        return None

    def reload_addons(self):
        return None

    def core_info(self):
        return {"update_available": True, "version": "2026.3.0", "version_latest": "2026.3.1"}

    def supervisor_info(self):
        return {"update_available": True, "version": "2026.03.0", "version_latest": "2026.03.1"}

    def os_info(self):
        return {"update_available": True, "version": "15.0", "version_latest": "15.1"}

    def list_addons(self):
        return [
            {
                "installed": True,
                "update_available": True,
                "slug": "esphome",
                "name": "ESPHome",
                "version": "1.0.0",
                "version_latest": "1.1.0",
            }
        ]


def test_update_planner_discovers_and_orders_updates() -> None:
    config = AppConfig.from_dict(
        {
            "update_strategy": "addons_last",
            "excluded_addons": [],
        }
    )
    planner = UpdatePlanner(
        config,
        PlannerClientStub(),
        PolicyEngine(config, logging.getLogger("test")),
        logging.getLogger("test"),
    )

    candidates = planner.discover(refresh=True)
    plan = planner.build_plan(
        candidates=candidates,
        snapshot=SystemSnapshot(
            free_disk_mb=4096,
            load_1m=1.0,
            free_memory_mb=1024,
            network_ok=True,
            api_ok=True,
            ha_state="running",
            supervisor_state="running",
        ),
        entity_states={},
        now=datetime(2026, 3, 25, 10, 0, tzinfo=UTC),
    )

    assert [item.component_type for item in plan.items] == ["supervisor", "core", "addon", "os"]
