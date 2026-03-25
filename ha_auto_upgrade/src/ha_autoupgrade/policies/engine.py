"""Run and candidate policy evaluation."""

from __future__ import annotations

import logging

from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.models import Decision, SystemSnapshot, UpdateCandidate
from ha_autoupgrade.utils.dates import blackout_match, within_time_window
from ha_autoupgrade.utils.versioning import compare_versions, is_patch_upgrade, rollout_bucket


class PolicyEngine:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger

    def evaluate_run(
        self,
        *,
        snapshot: SystemSnapshot,
        entity_states: dict[str, str],
        now,
        mode: str,
    ) -> Decision:
        reasons: list[str] = []
        if snapshot.free_disk_mb < self.config.min_free_disk_mb:
            reasons.append(
                f"Free disk below threshold ({snapshot.free_disk_mb}MB < {self.config.min_free_disk_mb}MB)"
            )
        if snapshot.load_1m is not None and snapshot.load_1m > self.config.max_cpu_load_1m:
            reasons.append(
                f"CPU load above threshold ({snapshot.load_1m:.2f} > {self.config.max_cpu_load_1m:.2f})"
            )
        if snapshot.free_memory_mb is not None and snapshot.free_memory_mb < self.config.min_free_memory_mb:
            reasons.append(
                f"Free memory below threshold ({snapshot.free_memory_mb}MB < {self.config.min_free_memory_mb}MB)"
            )
        if not snapshot.network_ok:
            reasons.append("Network connectivity check failed")
        if not snapshot.api_ok:
            reasons.append("Supervisor API availability check failed")
        if snapshot.ha_state not in {"running", "startup"}:
            reasons.append(f"Home Assistant state is not suitable for updates ({snapshot.ha_state})")

        if not within_time_window(now.astimezone(), self.config.maintenance_window):
            reasons.append("Current time is outside the configured maintenance window")

        blackout = blackout_match(now.astimezone(), self.config.blackout_dates)
        if blackout:
            reasons.append(f"Blackout date is active ({blackout})")

        weekday = now.astimezone().strftime("%a").lower()[:3]
        if weekday not in self.config.schedule_allowed_weekdays:
            reasons.append(f"Weekday {weekday} is not allowed by policy")

        if self.config.approval_entity:
            if entity_states.get(self.config.approval_entity) != "on":
                reasons.append(f"Approval entity {self.config.approval_entity} is not on")

        if self.config.ups_status_entity:
            if entity_states.get(self.config.ups_status_entity) != self.config.ups_required_state:
                reasons.append(
                    f"UPS entity {self.config.ups_status_entity} is not in required state {self.config.ups_required_state}"
                )

        for entity_id, required_state in self.config.require_entity_states.items():
            if entity_states.get(entity_id) != required_state:
                reasons.append(f"Required entity state mismatch for {entity_id} (need {required_state})")

        if (
            self.config.skip_if_someone_home_entity
            and entity_states.get(self.config.skip_if_someone_home_entity) == "home"
        ):
            reasons.append("Presence rule blocked updates because someone is home")

        media_state = entity_states.get(self.config.skip_if_media_playing_entity, "")
        if (
            self.config.skip_if_media_playing_entity
            and media_state not in {"", "off", "idle", "paused"}
        ):
            reasons.append("Media playback rule blocked updates")

        if (
            self.config.skip_if_critical_mode_entity
            and entity_states.get(self.config.skip_if_critical_mode_entity) == "on"
        ):
            reasons.append("Critical mode rule blocked updates")

        if (
            self.config.skip_if_alarm_armed_away_entity
            and entity_states.get(self.config.skip_if_alarm_armed_away_entity) == "armed_away"
        ):
            reasons.append("Alarm armed away rule blocked updates")

        if (
            self.config.skip_if_vacuum_cleaning_entity
            and entity_states.get(self.config.skip_if_vacuum_cleaning_entity) == "cleaning"
        ):
            reasons.append("Vacuum cleaning rule blocked updates")

        if (
            self.config.unstable_binary_sensor_entity
            and entity_states.get(self.config.unstable_binary_sensor_entity) == "on"
        ):
            reasons.append("Power/network instability sensor is active")

        return Decision(allowed=not reasons, reasons=reasons)

    def evaluate_candidate(self, candidate: UpdateCandidate) -> Decision:
        reasons: list[str] = []
        if not self.config.update_type_enabled(candidate.component_type):
            reasons.append(f"Updates for {candidate.component_type} are disabled")

        if candidate.component_type == "addon" and candidate.slug in self.config.excluded_addons:
            reasons.append(f"Add-on {candidate.slug} is excluded")

        pin_key = candidate.slug or candidate.component_type
        pinned_version = self.config.pinned_versions.get(pin_key)
        if pinned_version and compare_versions(candidate.target_version, pinned_version) > 0:
            reasons.append(f"Pinned version blocks update above {pinned_version}")

        minimum_version = self.config.minimum_required_versions.get(pin_key)
        if minimum_version and compare_versions(candidate.target_version, minimum_version) < 0:
            reasons.append(
                f"Target version {candidate.target_version} is below required minimum {minimum_version}"
            )

        if self.config.security_only_mode:
            if candidate.security is True:
                pass
            elif not is_patch_upgrade(candidate.current_version, candidate.target_version):
                reasons.append(
                    "Security-only mode is enabled and this update is not marked as security or a patch-level update"
                )

        if self.config.staged_rollout_enabled and candidate.component_type == "addon":
            bucket = rollout_bucket(
                self.config.staged_rollout_seed,
                f"{candidate.slug}:{candidate.target_version}",
            )
            if bucket >= self.config.staged_rollout_percent:
                reasons.append(
                    f"Add-on {candidate.slug} is outside the staged rollout percentage ({bucket} >= {self.config.staged_rollout_percent})"
                )

        return Decision(allowed=not reasons, reasons=reasons)
