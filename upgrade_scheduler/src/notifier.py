"""Notification helper for Home Assistant Upgrade Scheduler.

Sends persistent notifications to the Home Assistant UI and also writes
summary lines to the add-on log.
"""

import logging

from supervisor_api import SupervisorClient, SupervisorAPIError

logger = logging.getLogger(__name__)

ADDON_NAME = "Upgrade Scheduler"


class Notifier:
    """Sends update-status notifications via the HA Supervisor API."""

    def __init__(
        self,
        client: SupervisorClient,
        notify_on_success: bool = True,
        notify_on_failure: bool = True,
        silent_mode: bool = False,
    ) -> None:
        self._client = client
        self._on_success = notify_on_success
        self._on_failure = notify_on_failure
        self._silent = silent_mode

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def notify_success(self, summary: str) -> None:
        """Notify that the update run completed successfully."""
        logger.info("Update run SUCCESS: %s", summary)
        if self._silent or not self._on_success:
            return
        self._send(f"✅ {ADDON_NAME}: Update Successful", summary)

    def notify_failure(self, summary: str) -> None:
        """Notify that the update run failed."""
        logger.error("Update run FAILURE: %s", summary)
        if self._silent or not self._on_failure:
            return
        self._send(f"❌ {ADDON_NAME}: Update Failed", summary)

    def notify_info(self, message: str) -> None:
        """Send an informational notification (always, regardless of silent mode)."""
        logger.info(message)
        if self._silent:
            return
        self._send(f"ℹ️ {ADDON_NAME}", message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, title: str, message: str) -> None:
        try:
            self._client.send_notification(title, message)
        except SupervisorAPIError as exc:
            logger.warning("Could not send notification '%s': %s", title, exc)
