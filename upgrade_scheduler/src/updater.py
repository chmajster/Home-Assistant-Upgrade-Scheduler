"""Update executor for Home Assistant Upgrade Scheduler.

Handles the actual update of Core, Supervisor and individual add-ons.
Supports rollback to a pre-update backup on failure.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from supervisor_api import SupervisorClient, SupervisorAPIError
from backup_manager import BackupManager

logger = logging.getLogger(__name__)


@dataclass
class UpdateReport:
    """Summary of a single update run."""

    core_updated: bool = False
    supervisor_updated: bool = False
    addons_updated: List[str] = field(default_factory=list)
    addons_failed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    rolled_back: bool = False
    backup_slug: Optional[str] = None

    @property
    def success(self) -> bool:
        return len(self.errors) == 0 and len(self.addons_failed) == 0

    def summary(self) -> str:
        parts = []
        if self.core_updated:
            parts.append("Core updated")
        if self.supervisor_updated:
            parts.append("Supervisor updated")
        if self.addons_updated:
            parts.append(f"Add-ons updated: {', '.join(self.addons_updated)}")
        if self.addons_failed:
            parts.append(f"Add-ons FAILED: {', '.join(self.addons_failed)}")
        if self.errors:
            parts.append(f"Errors: {'; '.join(self.errors)}")
        if self.rolled_back:
            parts.append("System rolled back to backup")
        if not parts:
            return "No updates were available or required."
        return " | ".join(parts)


class Updater:
    """Executes Core, Supervisor, and add-on updates."""

    def __init__(
        self,
        client: SupervisorClient,
        backup_manager: Optional[BackupManager] = None,
        update_core: bool = True,
        update_supervisor: bool = True,
        update_addons: bool = True,
        addon_exclude: Optional[List[str]] = None,
        force_update: bool = False,
        rollback_on_failure: bool = False,
    ) -> None:
        self._client = client
        self._backup_manager = backup_manager
        self._update_core = update_core
        self._update_supervisor = update_supervisor
        self._update_addons = update_addons
        self._addon_exclude = set(addon_exclude or [])
        self._force_update = force_update
        self._rollback_on_failure = rollback_on_failure

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, pre_backup_slug: Optional[str] = None) -> UpdateReport:
        """Execute all configured updates and return a report."""
        report = UpdateReport(backup_slug=pre_backup_slug)

        if self._update_supervisor:
            self._do_update_supervisor(report)

        if self._update_core:
            self._do_update_core(report)

        if self._update_addons:
            self._do_update_addons(report)

        # Rollback if any failures occurred and rollback is enabled
        if not report.success and self._rollback_on_failure:
            self._attempt_rollback(report)

        return report

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _do_update_supervisor(self, report: UpdateReport) -> None:
        try:
            info = self._client.get_supervisor_info()
            if not self._needs_update(info):
                logger.info("Supervisor is already up-to-date.")
                return
            self._client.update_supervisor()
            report.supervisor_updated = True
            logger.info("Supervisor updated successfully.")
        except SupervisorAPIError as exc:
            msg = f"Supervisor update failed: {exc}"
            logger.error(msg)
            report.errors.append(msg)

    def _do_update_core(self, report: UpdateReport) -> None:
        try:
            info = self._client.get_core_info()
            if not self._needs_update(info):
                logger.info("Core is already up-to-date.")
                return
            self._client.update_core()
            report.core_updated = True
            logger.info("Core updated successfully.")
        except SupervisorAPIError as exc:
            msg = f"Core update failed: {exc}"
            logger.error(msg)
            report.errors.append(msg)

    def _do_update_addons(self, report: UpdateReport) -> None:
        try:
            addons = self._client.get_addons()
        except SupervisorAPIError as exc:
            msg = f"Could not list add-ons: {exc}"
            logger.error(msg)
            report.errors.append(msg)
            return

        for addon in addons:
            slug = addon.get("slug", "")
            name = addon.get("name", slug)

            if slug in self._addon_exclude:
                logger.info("Skipping excluded add-on: %s (%s).", name, slug)
                continue

            if not self._needs_update(addon):
                logger.debug("Add-on %s (%s) is up-to-date.", name, slug)
                continue

            try:
                self._client.update_addon(slug)
                report.addons_updated.append(name)
                logger.info("Add-on %s (%s) updated successfully.", name, slug)
            except SupervisorAPIError as exc:
                msg = f"Add-on {name} ({slug}) update failed: {exc}"
                logger.error(msg)
                report.addons_failed.append(name)

    def _needs_update(self, info: dict) -> bool:
        """Return True when an update is available (or when forced)."""
        if self._force_update:
            return True
        # The Supervisor API exposes 'update_available' on most entities.
        return bool(info.get("update_available", False))

    def _attempt_rollback(self, report: UpdateReport) -> None:
        if not self._backup_manager or not report.backup_slug:
            logger.warning(
                "Rollback requested but no backup manager or backup slug available."
            )
            return
        logger.warning(
            "Update failures detected; attempting rollback to backup %s…",
            report.backup_slug,
        )
        ok = self._backup_manager.restore_backup(report.backup_slug)
        report.rolled_back = ok
        if ok:
            logger.info("Rollback completed successfully.")
        else:
            logger.error("Rollback FAILED.  Manual intervention may be required.")
