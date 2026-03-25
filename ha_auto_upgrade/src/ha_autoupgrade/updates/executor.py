"""Update plan execution."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import time

from ha_autoupgrade.api.supervisor import SupervisorAPIError, SupervisorClient
from ha_autoupgrade.backups.manager import BackupManager
from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.models import RunSummary, UpdateCandidate, UpdatePlan, UpdateResult
from ha_autoupgrade.notifications.manager import NotificationManager


class UpdateExecutor:
    def __init__(
        self,
        config: AppConfig,
        client: SupervisorClient,
        backup_manager: BackupManager,
        notifier: NotificationManager,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.client = client
        self.backup_manager = backup_manager
        self.notifier = notifier
        self.logger = logger

    def execute(
        self,
        *,
        plan: UpdatePlan,
        trigger: str,
        mode: str,
        backup_id: str | None = None,
    ) -> RunSummary:
        started_at = datetime.now(UTC)
        results: list[UpdateResult] = []
        skipped_reasons: list[str] = []
        active_backup_id = backup_id
        self.logger.info(
            "Executing update plan: trigger=%s mode=%s items=%s",
            trigger,
            mode,
            [f"{item.component_type}:{item.name}" for item in plan.items],
        )

        if not plan.items:
            return RunSummary(
                trigger=trigger,
                mode=mode,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                status="skipped",
                results=[],
                skipped_reasons=["No updates matched the active policy"],
                detected_updates=[],
            )

        if active_backup_id is None and not self.config.dry_run and not self.config.notify_only_mode:
            active_backup_id = self.backup_manager.create_pre_update_backup(trigger)
            self.logger.info("Executor created backup: %s", active_backup_id)

        for candidate in plan.items:
            self.logger.info(
                "Starting update for %s (%s -> %s)",
                candidate.name,
                candidate.current_version,
                candidate.target_version,
            )
            self.notifier.send(
                "start",
                f"HA AutoUpgrade starting {candidate.name}",
                {
                    "event": "start",
                    "component_type": candidate.component_type,
                    "name": candidate.name,
                    "previous_version": candidate.current_version,
                    "target_version": candidate.target_version,
                    "backup_id": active_backup_id,
                },
            )
            result = self._execute_candidate(candidate, backup_id=active_backup_id)
            results.append(result)
            self.logger.info(
                "Finished update for %s with result=%s duration=%.2fs",
                candidate.name,
                result.result,
                result.duration_seconds,
            )
            if result.result == "failed":
                skipped_reasons.append(f"{candidate.name}: {result.reason}")
            if self.config.delay_between_updates_seconds > 0 and candidate is not plan.items[-1]:
                time.sleep(self.config.delay_between_updates_seconds)

        completed_at = datetime.now(UTC)
        if all(result.result in {"updated", "simulated", "notified"} for result in results):
            status = "success"
        elif any(result.result in {"updated", "simulated", "notified"} for result in results):
            status = "partial"
        else:
            status = "failed"

        if status == "failed" and active_backup_id:
            rollback = self.backup_manager.attempt_rollback(active_backup_id)
            skipped_reasons.append(f"Rollback status: {rollback.get('result')}")
            self.logger.warning("Rollback result after failed run: %s", rollback)

        self.logger.info("Update plan execution finished with status=%s", status)
        return RunSummary(
            trigger=trigger,
            mode=mode,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            results=results,
            skipped_reasons=skipped_reasons,
            backup_id=active_backup_id,
            detected_updates=plan.items,
        )

    def _execute_candidate(self, candidate: UpdateCandidate, *, backup_id: str | None) -> UpdateResult:
        started = time.monotonic()
        if self.config.dry_run:
            self.logger.info("Dry-run active, simulating update for %s", candidate.name)
            return UpdateResult(
                component_type=candidate.component_type,
                slug=candidate.slug,
                name=candidate.name,
                previous_version=candidate.current_version,
                target_version=candidate.target_version,
                result="simulated",
                duration_seconds=time.monotonic() - started,
                reason="Dry-run mode enabled",
                backup_id=backup_id,
            )

        if self.config.notify_only_mode or self.config.check_only_mode:
            self.logger.info("Notify/check-only mode active, not installing %s", candidate.name)
            return UpdateResult(
                component_type=candidate.component_type,
                slug=candidate.slug,
                name=candidate.name,
                previous_version=candidate.current_version,
                target_version=candidate.target_version,
                result="notified",
                duration_seconds=time.monotonic() - started,
                reason="Notify-only or check-only mode enabled",
                backup_id=backup_id,
            )

        try:
            job_id: str | None = None
            if candidate.component_type == "core":
                response = self.client.update_core(candidate.target_version, backup=False)
            elif candidate.component_type == "supervisor":
                response = self.client.update_supervisor(candidate.target_version)
            elif candidate.component_type == "os":
                response = self.client.update_os(candidate.target_version)
            elif candidate.component_type == "addon" and candidate.slug:
                response = self.client.update_addon(candidate.slug, backup=False, background=True)
            else:
                raise SupervisorAPIError(f"Unsupported component type: {candidate.component_type}")

            if isinstance(response, dict):
                job_id = response.get("job_id")
                if job_id:
                    self.logger.info("Waiting for Supervisor job %s (%s)", job_id, candidate.name)
                    self.client.wait_for_job(job_id)

            health_ok = self._verify_health()
            return UpdateResult(
                component_type=candidate.component_type,
                slug=candidate.slug,
                name=candidate.name,
                previous_version=candidate.current_version,
                target_version=candidate.target_version,
                result="updated" if health_ok else "failed",
                duration_seconds=time.monotonic() - started,
                reason="" if health_ok else "Post-update health verification failed",
                backup_id=backup_id,
                job_id=job_id,
                health_ok=health_ok,
            )
        except Exception as err:
            self.logger.exception("Failed to update %s", candidate.name)
            return UpdateResult(
                component_type=candidate.component_type,
                slug=candidate.slug,
                name=candidate.name,
                previous_version=candidate.current_version,
                target_version=candidate.target_version,
                result="failed",
                duration_seconds=time.monotonic() - started,
                reason=str(err),
                backup_id=backup_id,
                health_ok=False,
            )

    def _verify_health(self) -> bool:
        try:
            if not self.client.ping():
                return False
            core_config = self.client.core_config()
            return core_config.get("state", "running") in {"running", "startup"}
        except Exception:
            return False
