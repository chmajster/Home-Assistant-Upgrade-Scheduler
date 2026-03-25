"""Supervisor API client for Home Assistant Upgrade Scheduler.

All communication with the HA Supervisor happens through its HTTP API, which is
available inside add-on containers at http://supervisor.  The token is passed via
the SUPERVISOR_TOKEN environment variable.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import requests

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
BASE_URL = "http://supervisor"

logger = logging.getLogger(__name__)


class SupervisorAPIError(Exception):
    """Raised when a Supervisor API call fails."""


class SupervisorClient:
    """Thin wrapper around the Supervisor REST API."""

    def __init__(self, token: str = SUPERVISOR_TOKEN, timeout: int = 60) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        try:
            resp = self._session.get(url, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.RequestException as exc:
            raise SupervisorAPIError(f"GET {path} failed: {exc}") from exc

    def _post(self, path: str, payload: Optional[dict] = None) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        try:
            resp = self._session.post(
                url, json=payload or {}, timeout=self._timeout
            )
            resp.raise_for_status()
            body = resp.json()
            return body.get("data", {})
        except requests.RequestException as exc:
            raise SupervisorAPIError(f"POST {path} failed: {exc}") from exc

    def _delete(self, path: str) -> None:
        url = f"{BASE_URL}{path}"
        try:
            resp = self._session.delete(url, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise SupervisorAPIError(f"DELETE {path} failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Host / system info
    # ------------------------------------------------------------------

    def get_host_info(self) -> Dict[str, Any]:
        return self._get("/host/info")

    def get_supervisor_info(self) -> Dict[str, Any]:
        return self._get("/supervisor/info")

    def get_core_info(self) -> Dict[str, Any]:
        return self._get("/core/info")

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def update_supervisor(self) -> None:
        logger.info("Requesting Supervisor update…")
        self._post("/supervisor/update")

    def update_core(self) -> None:
        logger.info("Requesting Core update…")
        self._post("/core/update")

    def get_addons(self) -> List[Dict[str, Any]]:
        data = self._get("/addons")
        return data.get("addons", [])

    def get_addon_info(self, slug: str) -> Dict[str, Any]:
        return self._get(f"/addons/{slug}/info")

    def update_addon(self, slug: str) -> None:
        logger.info("Requesting add-on %s update…", slug)
        self._post(f"/addons/{slug}/update")

    # ------------------------------------------------------------------
    # Backups
    # ------------------------------------------------------------------

    def create_full_backup(self, name: str) -> str:
        """Create a full backup and return its slug."""
        logger.info("Creating full backup '%s'…", name)
        data = self._post("/backups/new/full", {"name": name})
        slug = data.get("slug", "")
        logger.info("Backup created: slug=%s", slug)
        return slug

    def list_backups(self) -> List[Dict[str, Any]]:
        data = self._get("/backups")
        return data.get("backups", [])

    def remove_backup(self, slug: str) -> None:
        logger.info("Removing old backup %s…", slug)
        self._delete(f"/backups/{slug}")

    def restore_full_backup(self, slug: str) -> None:
        logger.info("Restoring full backup %s…", slug)
        self._post(f"/backups/{slug}/restore/full")

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def send_notification(self, title: str, message: str) -> None:
        """Create a persistent notification visible in the HA UI."""
        logger.debug("Sending notification: %s", title)
        self._post(
            "/core/api/services/persistent_notification/create",
            {"title": title, "message": message},
        )
