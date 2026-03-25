from __future__ import annotations

from datetime import UTC, datetime
import logging

from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.models import SystemSnapshot, UpdateCandidate
from ha_autoupgrade.policies.engine import PolicyEngine


def test_candidate_policy_blocks_excluded_addon_and_pin() -> None:
    config = AppConfig.from_dict(
        {
            "excluded_addons": ["esphome"],
            "pinned_versions": ["mosquitto=1.2.0"],
        }
    )
    engine = PolicyEngine(config, logging.getLogger("test"))

    excluded = UpdateCandidate(
        component_type="addon",
        slug="esphome",
        name="ESPHome",
        current_version="1.0.0",
        target_version="1.1.0",
    )
    pinned = UpdateCandidate(
        component_type="addon",
        slug="mosquitto",
        name="Mosquitto",
        current_version="1.1.0",
        target_version="1.3.0",
    )

    assert engine.evaluate_candidate(excluded).allowed is False
    assert engine.evaluate_candidate(pinned).allowed is False


def test_run_policy_blocks_presence_and_bad_resources() -> None:
    config = AppConfig.from_dict(
        {
            "skip_if_someone_home_entity": "person.chris",
            "approval_entity": "input_boolean.approved",
            "maintenance_window": "22:00-06:00",
        }
    )
    engine = PolicyEngine(config, logging.getLogger("test"))
    snapshot = SystemSnapshot(
        free_disk_mb=100,
        load_1m=6.5,
        free_memory_mb=100,
        network_ok=False,
        api_ok=False,
        ha_state="stopped",
        supervisor_state="stopped",
    )
    decision = engine.evaluate_run(
        snapshot=snapshot,
        entity_states={
            "person.chris": "home",
            "input_boolean.approved": "off",
        },
        now=datetime(2026, 3, 25, 12, 0, tzinfo=UTC),
        mode="install",
    )

    assert decision.allowed is False
    assert any("someone is home" in reason for reason in decision.reasons)
    assert any("Approval entity" in reason for reason in decision.reasons)
    assert any("Free disk below threshold" in reason for reason in decision.reasons)


def test_manual_install_bypasses_schedule_day_and_maintenance_window() -> None:
    config = AppConfig.from_dict(
        {
            "install_days": "sun",
            "install_hour": "03:00",
            "maintenance_window": "22:00-06:00",
        }
    )
    engine = PolicyEngine(config, logging.getLogger("test"))
    snapshot = SystemSnapshot(
        free_disk_mb=4096,
        load_1m=0.5,
        free_memory_mb=1024,
        network_ok=True,
        api_ok=True,
        ha_state="running",
        supervisor_state="running",
    )
    now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)

    manual = engine.evaluate_run(snapshot=snapshot, entity_states={}, now=now, mode="manual_install")
    scheduled = engine.evaluate_run(
        snapshot=snapshot,
        entity_states={},
        now=now,
        mode="scheduled_install",
    )

    assert manual.allowed is True
    assert scheduled.allowed is False
    assert any("maintenance window" in reason or "not allowed by policy" in reason for reason in scheduled.reasons)
