"""Supervisor and Home Assistant API client."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time
from typing import Any

import requests

from ha_autoupgrade.constants import DEFAULT_CORE_API_URL, DEFAULT_SUPERVISOR_URL


class SupervisorAPIError(RuntimeError):
    """Raised when the Supervisor or Home Assistant API cannot be used safely."""


@dataclass(slots=True)
class SupervisorClient:
    logger: logging.Logger
    supervisor_url: str = DEFAULT_SUPERVISOR_URL
    core_api_url: str = DEFAULT_CORE_API_URL
    timeout_seconds: int = 30
    max_attempts: int = 4
    backoff_seconds: int = 2

    def __post_init__(self) -> None:
        token = os.getenv("SUPERVISOR_TOKEN", "")
        if not token:
            raise SupervisorAPIError("SUPERVISOR_TOKEN is not available")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def configure_retries(self, max_attempts: int, backoff_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        use_core_api: bool = False,
        accept_not_found: bool = False,
    ) -> Any:
        base_url = self.core_api_url if use_core_api else self.supervisor_url
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if accept_not_found and response.status_code == 404:
                    return None
                response.raise_for_status()
                if not response.content:
                    return {}
                data = response.json()
                if isinstance(data, dict) and data.get("result") == "ok" and "data" in data:
                    return data["data"]
                if isinstance(data, dict) and "data" in data and len(data) == 1:
                    return data["data"]
                return data
            except (requests.RequestException, ValueError) as err:
                last_error = err
                if attempt >= self.max_attempts:
                    break
                time.sleep(self.backoff_seconds * attempt)
        raise SupervisorAPIError(f"{method} {path} failed: {last_error}") from last_error

    def ping(self) -> bool:
        try:
            self._request("GET", "/supervisor/ping")
            return True
        except SupervisorAPIError:
            return False

    def root_info(self) -> dict[str, Any]:
        return self._request("GET", "/info")

    def core_info(self) -> dict[str, Any]:
        return self._request("GET", "/core/info")

    def supervisor_info(self) -> dict[str, Any]:
        return self._request("GET", "/supervisor/info")

    def os_info(self) -> dict[str, Any] | None:
        return self._request("GET", "/os/info", accept_not_found=True)

    def available_updates(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/available_updates")
        return response.get("available_updates", response)

    def reload_updates(self) -> None:
        self._request("POST", "/reload_updates")

    def reload_store(self) -> None:
        self._request("POST", "/store/reload")

    def reload_addons(self) -> None:
        self._request("POST", "/addons/reload")

    def list_addons(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/addons")
        return response.get("addons", response)

    def addon_info(self, slug: str) -> dict[str, Any]:
        return self._request("GET", f"/addons/{slug}/info")

    def set_addon_options(self, slug: str, options: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/addons/{slug}/options", payload={"options": options})

    def validate_addon_options(self, slug: str, options: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/addons/{slug}/options/validate", payload=options)

    def update_core(self, version: str | None = None, backup: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"backup": backup}
        if version:
            payload["version"] = version
        return self._request("POST", "/core/update", payload=payload)

    def update_supervisor(self, version: str | None = None) -> dict[str, Any]:
        payload = {"version": version} if version else {}
        return self._request("POST", "/supervisor/update", payload=payload)

    def update_os(self, version: str | None = None) -> dict[str, Any]:
        payload = {"version": version} if version else {}
        return self._request("POST", "/os/update", payload=payload)

    def update_addon(self, slug: str, backup: bool = False, background: bool = True) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/store/addons/{slug}/update",
            payload={"backup": backup, "background": background},
        )

    def restart_addon(self, slug: str) -> dict[str, Any]:
        return self._request("POST", f"/addons/{slug}/restart")

    def list_backups(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/backups")
        return response.get("backups", response)

    def create_full_backup(
        self,
        *,
        name: str,
        password: str = "",
        compressed: bool = True,
        background: bool = True,
        exclude_database: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "name": name,
            "password": password or None,
            "compressed": compressed,
            "background": background,
            "homeassistant_exclude_database": exclude_database,
        }
        return self._request("POST", "/backups/new/full", payload=payload)

    def create_partial_backup(
        self,
        *,
        name: str,
        addons: list[str],
        include_homeassistant: bool = True,
        folders: list[str] | None = None,
        password: str = "",
        compressed: bool = True,
        background: bool = True,
        exclude_database: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "name": name,
            "password": password or None,
            "homeassistant": include_homeassistant,
            "addons": addons,
            "folders": folders or [],
            "compressed": compressed,
            "background": background,
            "homeassistant_exclude_database": exclude_database,
        }
        return self._request("POST", "/backups/new/partial", payload=payload)

    def delete_backup(self, slug: str) -> None:
        self._request("DELETE", f"/backups/{slug}")

    def restore_full_backup(self, slug: str, password: str = "", background: bool = True) -> dict[str, Any]:
        payload = {"password": password or None, "background": background}
        return self._request("POST", f"/backups/{slug}/restore/full", payload=payload)

    def restore_partial_backup(
        self,
        slug: str,
        *,
        include_homeassistant: bool = False,
        addons: list[str] | None = None,
        folders: list[str] | None = None,
        password: str = "",
        background: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "homeassistant": include_homeassistant,
            "addons": addons or [],
            "folders": folders or [],
            "password": password or None,
            "background": background,
        }
        return self._request("POST", f"/backups/{slug}/restore/partial", payload=payload)

    def job_info(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}")

    def wait_for_job(self, job_id: str, timeout_seconds: int = 1800, poll_seconds: int = 5) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            job = self.job_info(job_id)
            if job.get("done"):
                return job
            time.sleep(poll_seconds)
        raise SupervisorAPIError(f"Timed out waiting for job {job_id}")

    def core_api_get(self, path: str) -> Any:
        return self._request("GET", path, use_core_api=True)

    def core_api_post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, payload=payload, use_core_api=True)

    def core_config(self) -> dict[str, Any]:
        return self.core_api_get("/config")

    def entity_state(self, entity_id: str) -> dict[str, Any] | None:
        return self._request("GET", f"/states/{entity_id}", use_core_api=True, accept_not_found=True)

    def call_service(self, service_name: str, payload: dict[str, Any] | None = None) -> Any:
        domain, service = service_name.split(".", maxsplit=1)
        return self.core_api_post(f"/services/{domain}/{service}", payload=payload or {})

    def create_persistent_notification(self, title: str, message: str, notification_id: str) -> None:
        self.call_service(
            "persistent_notification.create",
            {
                "title": title,
                "message": message,
                "notification_id": notification_id,
            },
        )

    def fire_event(self, event_type: str, payload: dict[str, Any]) -> Any:
        return self.core_api_post(f"/events/{event_type}", payload)
