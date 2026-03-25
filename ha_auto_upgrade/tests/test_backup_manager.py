from __future__ import annotations

import logging

from ha_autoupgrade.backups.manager import BackupManager
from ha_autoupgrade.config import AppConfig


class BackupClientStub:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def create_full_backup(self, **_kwargs):
        return {"job_id": "job-1"}

    def wait_for_job(self, _job_id: str):
        return {"slug": "backup-new"}

    def list_backups(self):
        return [
            {"slug": "backup-new", "name": "[HA AutoUpgrade] new", "date": "2026-03-25T10:00:00Z"},
            {"slug": "backup-old", "name": "[HA AutoUpgrade] old", "date": "2026-03-20T10:00:00Z"},
        ]

    def delete_backup(self, slug: str):
        self.deleted.append(slug)


def test_backup_manager_creates_backup_and_applies_retention() -> None:
    client = BackupClientStub()
    config = AppConfig.from_dict({"backup_retention": 1})
    manager = BackupManager(config, client, logging.getLogger("test"))

    backup_id = manager.create_pre_update_backup("schedule")

    assert backup_id == "backup-new"
    assert client.deleted == ["backup-old"]
