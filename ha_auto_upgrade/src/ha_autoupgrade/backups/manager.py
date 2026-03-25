"""Backup workflow integration."""

from __future__ import annotations

from datetime import UTC, datetime
import logging

from ha_autoupgrade.api.supervisor import SupervisorClient
from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.constants import BACKUP_NAME_PREFIX


class BackupManager:
    def __init__(self, config: AppConfig, client: SupervisorClient, logger: logging.Logger) -> None:
        self.config = config
        self.client = client
        self.logger = logger

    def create_pre_update_backup(self, trigger: str) -> str | None:
        if not self.config.create_backup:
            self.logger.info("Backup creation is disabled")
            return None

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        name = f"{BACKUP_NAME_PREFIX} {timestamp} ({trigger})"
        self.logger.info("Creating %s backup", self.config.backup_mode)
        if self.config.backup_mode == "partial":
            response = self.client.create_partial_backup(
                name=name,
                addons=self.config.backup_partial_addons,
                include_homeassistant=True,
                password=self.config.backup_password,
                exclude_database=False,
            )
        else:
            response = self.client.create_full_backup(
                name=name,
                password=self.config.backup_password,
                exclude_database=False,
            )

        job_id = response.get("job_id")
        slug = response.get("slug")
        if job_id and not slug:
            job = self.client.wait_for_job(job_id)
            slug = job.get("slug") or job.get("reference")
        if not slug:
            raise RuntimeError("Backup creation did not return a backup slug")
        self.logger.info("Backup created successfully: %s", slug)
        self.cleanup_retention()
        return slug

    def cleanup_retention(self) -> None:
        if self.config.backup_retention <= 0:
            return
        backups = [
            item
            for item in self.client.list_backups()
            if str(item.get("name", "")).startswith(BACKUP_NAME_PREFIX)
        ]
        backups.sort(key=lambda item: item.get("date", ""), reverse=True)
        for backup in backups[self.config.backup_retention :]:
            slug = backup.get("slug")
            if slug:
                self.logger.info("Deleting retained backup %s", slug)
                self.client.delete_backup(slug)

    def attempt_rollback(self, backup_id: str) -> dict[str, str]:
        if not self.config.rollback_on_failure or not backup_id:
            return {"result": "disabled", "message": "Rollback disabled"}
        if self.config.backup_mode != "full":
            return {
                "result": "manual_required",
                "message": "Automatic rollback is only attempted for full backups",
            }
        response = self.client.restore_full_backup(backup_id, password=self.config.backup_password)
        return {
            "result": "requested",
            "message": "Full restore requested via Supervisor",
            "job_id": response.get("job_id", ""),
        }
