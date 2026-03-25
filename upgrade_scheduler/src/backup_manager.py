"""Backup management for Home Assistant Upgrade Scheduler.

Creates a full system backup before any update run and enforces a retention
policy to avoid filling up storage with stale backups.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from supervisor_api import SupervisorClient, SupervisorAPIError

logger = logging.getLogger(__name__)


class BackupManager:
    """Creates and manages automatic backups around update operations."""

    def __init__(
        self,
        client: SupervisorClient,
        name_prefix: str = "upgrade-scheduler",
        keep_last: int = 5,
    ) -> None:
        self._client = client
        self._prefix = name_prefix
        self._keep_last = max(1, keep_last)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def create_backup(self) -> Optional[str]:
        """Create a timestamped full backup.

        Returns the backup slug on success, or *None* on failure.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        name = f"{self._prefix}-{timestamp}"
        try:
            slug = self._client.create_full_backup(name)
            logger.info("Backup created successfully (slug=%s, name=%s).", slug, name)
            return slug
        except SupervisorAPIError as exc:
            logger.error("Failed to create backup: %s", exc)
            return None

    def enforce_retention(self) -> None:
        """Remove old backups created by this addon, keeping only the most recent ones."""
        try:
            all_backups = self._client.list_backups()
        except SupervisorAPIError as exc:
            logger.error("Cannot list backups for retention enforcement: %s", exc)
            return

        # Filter to backups whose name starts with our prefix.
        managed = [
            b
            for b in all_backups
            if b.get("name", "").startswith(self._prefix)
        ]

        # Sort by date descending (newest first).  The Supervisor returns
        # backups with a 'date' ISO-8601 string.
        managed.sort(key=lambda b: b.get("date", ""), reverse=True)

        to_remove = managed[self._keep_last:]
        for backup in to_remove:
            slug = backup.get("slug", "")
            name = backup.get("name", slug)
            logger.info("Retention: removing old backup '%s' (slug=%s).", name, slug)
            try:
                self._client.remove_backup(slug)
            except SupervisorAPIError as exc:
                logger.warning("Failed to remove backup %s: %s", slug, exc)

    def restore_backup(self, slug: str) -> bool:
        """Restore a backup by slug.

        Returns True on success, False on failure.
        """
        try:
            self._client.restore_full_backup(slug)
            logger.info("Backup %s restored successfully.", slug)
            return True
        except SupervisorAPIError as exc:
            logger.error("Failed to restore backup %s: %s", slug, exc)
            return False
