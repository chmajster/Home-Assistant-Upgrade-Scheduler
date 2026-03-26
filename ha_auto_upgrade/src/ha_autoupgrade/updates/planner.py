"""Discover and plan updates."""

from __future__ import annotations

from datetime import datetime
import logging

from ha_autoupgrade.api.supervisor import SupervisorClient
from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.models import SystemSnapshot, UpdateCandidate, UpdatePlan
from ha_autoupgrade.policies.engine import PolicyEngine


class UpdatePlanner:
    def __init__(
        self,
        config: AppConfig,
        client: SupervisorClient,
        policy_engine: PolicyEngine,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.client = client
        self.policy_engine = policy_engine
        self.logger = logger

    def discover(self, refresh: bool = True) -> list[UpdateCandidate]:
        self.logger.info("Discovering available updates (refresh=%s)", refresh)
        if refresh:
            self.client.refresh_updates()

        candidates: list[UpdateCandidate] = []

        core_info = self.client.core_info()
        if core_info.get("update_available"):
            candidates.append(
                UpdateCandidate(
                    component_type="core",
                    slug="core",
                    name="Home Assistant Core",
                    current_version=core_info.get("version", "unknown"),
                    target_version=core_info.get("version_latest", "unknown"),
                    security=core_info.get("security"),
                    metadata=core_info,
                )
            )

        supervisor_info = self.client.supervisor_info()
        if supervisor_info.get("update_available"):
            candidates.append(
                UpdateCandidate(
                    component_type="supervisor",
                    slug="supervisor",
                    name="Home Assistant Supervisor",
                    current_version=supervisor_info.get("version", "unknown"),
                    target_version=supervisor_info.get("version_latest", "unknown"),
                    security=supervisor_info.get("security"),
                    metadata=supervisor_info,
                )
            )

        os_info = self.client.os_info()
        if os_info and os_info.get("update_available"):
            candidates.append(
                UpdateCandidate(
                    component_type="os",
                    slug="os",
                    name="Home Assistant OS",
                    current_version=os_info.get("version", "unknown"),
                    target_version=os_info.get("version_latest", "unknown"),
                    security=os_info.get("security"),
                    metadata=os_info,
                )
            )

        for addon in self.client.list_addons():
            if addon.get("installed") and addon.get("update_available"):
                candidates.append(
                    UpdateCandidate(
                        component_type="addon",
                        slug=addon.get("slug"),
                        name=addon.get("name", addon.get("slug", "Addon")),
                        current_version=addon.get("version", "unknown"),
                        target_version=addon.get("version_latest", "unknown"),
                        security=addon.get("security"),
                        metadata=addon,
                    )
                )

        self.logger.info(
            "Discovered updates: %s",
            [f"{item.component_type}:{item.name}->{item.target_version}" for item in candidates],
        )
        return candidates

    def build_plan(
        self,
        *,
        candidates: list[UpdateCandidate],
        snapshot: SystemSnapshot,
        entity_states: dict[str, str],
        now: datetime,
    ) -> UpdatePlan:
        self.logger.info("Building update plan for %d discovered candidates", len(candidates))
        selected: list[UpdateCandidate] = []
        skipped: list[dict[str, object]] = []
        for candidate in candidates:
            decision = self.policy_engine.evaluate_candidate(candidate)
            if decision.allowed:
                selected.append(candidate)
            else:
                skipped.append(
                    {
                        "candidate": candidate.to_dict(),
                        "reasons": decision.reasons,
                    }
                )

        selected.sort(key=self._sort_key)
        if self.config.max_updates_per_run > 0:
            selected = selected[: self.config.max_updates_per_run]

        self.logger.info(
            "Update plan built: selected=%s skipped=%d",
            [f"{item.component_type}:{item.name}" for item in selected],
            len(skipped),
        )
        return UpdatePlan(items=selected, skipped=skipped, generated_at=now)

    def _sort_key(self, candidate: UpdateCandidate) -> tuple[int, str]:
        strategy = self.config.update_strategy
        if strategy == "addons_first":
            order = {"addon": 0, "supervisor": 1, "core": 2, "os": 3}
        elif strategy == "core_first":
            order = {"core": 0, "supervisor": 1, "addon": 2, "os": 3}
        else:
            order = {"supervisor": 0, "core": 1, "addon": 2, "os": 3}
        return (order.get(candidate.component_type, 99), candidate.name.lower())
