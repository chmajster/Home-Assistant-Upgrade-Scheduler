from __future__ import annotations

import json

from ha_autoupgrade.web.server import DashboardServer


class StubConfig:
    webhook_trigger_token = "secret"


class StubService:
    def __init__(self) -> None:
        self.config = StubConfig()
        self.queued: list[tuple[str, str, object]] = []
        self.tasks = [
            {
                "id": "task-check",
                "task_type": "auto_check_update",
                "weekdays": ["mon", "wed"],
                "hour": 4,
                "minute": 30,
                "enabled": True,
                "next_run": "2026-04-08T04:30:00+00:00",
                "category": "System",
                "owner": "HA AutoUpgrade",
                "name": "Auto Check Update",
                "action": "Automatyczne sprawdzanie aktualizacji",
            }
        ]

    def enqueue_action(self, action: str, source: str = "manual", payload=None) -> None:
        self.queued.append((action, source, payload))

    def status(self):
        return {
            "state": {
                "pending_updates": [],
                "last_check": None,
                "next_install": None,
                "last_backup": None,
                "last_run": None,
                "safe_mode_until": None,
            },
            "recent_history": [],
            "recent_logs": [],
            "config": {
                "install_days": "mon,wed",
                "install_hour": "04:30",
                "schedule_install_frequency": "weekly",
                "schedule_install_monthday": 15,
                "schedule_install_time_range_end": "",
            },
            "scheduled_tasks": self.tasks,
        }

    def health(self):
        return {
            "ok": True,
            "snapshot": {"ha_state": "running"},
            "safe_mode_until": None,
        }

    def export_diagnostics(self):
        return {"path": "/data/export.zip"}

    def self_test(self):
        return {"results": []}

    def import_configuration(self, payload):
        return {"status": "imported", "payload": payload}

    def list_schedule_tasks(self):
        return self.tasks

    def create_schedule_task(self, payload):
        item = {
            "id": "task-created",
            "task_type": payload["task_type"],
            "weekdays": payload["weekdays"],
            "hour": payload["hour"],
            "minute": payload.get("minute", 0),
            "enabled": payload.get("enabled", True),
            "next_run": "2026-04-09T03:00:00+00:00",
            "category": "System",
            "owner": "HA AutoUpgrade",
            "name": "Auto Update" if payload["task_type"] == "auto_update" else "Auto Check Update",
            "action": "Automatyczna instalacja aktualizacji"
            if payload["task_type"] == "auto_update"
            else "Automatyczne sprawdzanie aktualizacji",
        }
        self.tasks.append(item)
        return item

    def update_schedule_task(self, task_id, payload):
        for task in self.tasks:
            if task["id"] != task_id:
                continue
            task.update(payload)
            return task
        raise ValueError("not found")

    def set_schedule_task_enabled(self, task_id, enabled):
        return self.update_schedule_task(task_id, {"enabled": enabled})


def test_dashboard_api_accepts_local_requests() -> None:
    server = DashboardServer(StubService())
    status, content_type, payload = server.handle_request(
        method="GET",
        raw_path="/api/status",
        remote_addr="127.0.0.1",
    )

    assert status == 200
    assert "application/json" in content_type
    assert b"pending_updates" in payload


def test_dashboard_webhook_requires_token() -> None:
    service = StubService()
    server = DashboardServer(service)
    unauthorized = server.handle_request(method="POST", raw_path="/api/webhook/trigger")
    authorized = server.handle_request(method="POST", raw_path="/api/webhook/trigger?token=secret")

    assert unauthorized[0] == 401
    assert authorized[0] == 200
    assert service.queued == [("install", "webhook", None)]


def test_dashboard_check_install_action_is_available() -> None:
    service = StubService()
    server = DashboardServer(service)

    response = server.handle_request(
        method="POST",
        raw_path="/api/actions/check-install",
        remote_addr="127.0.0.1",
    )

    assert response[0] == 200
    assert service.queued == [("check_install", "dashboard", None)]


def test_dashboard_homepage_contains_check_install_button() -> None:
    server = DashboardServer(StubService())

    response = server.handle_request(
        method="GET",
        raw_path="/",
        remote_addr="127.0.0.1",
    )

    assert response[0] == 200
    assert b"/api/actions/check-install" in response[2]


def test_dashboard_homepage_contains_bootstrap_task_modal() -> None:
    server = DashboardServer(StubService())

    response = server.handle_request(
        method="GET",
        raw_path="/?lang=pl",
        remote_addr="127.0.0.1",
    )

    assert response[0] == 200
    assert b"id=\"create-task-btn\"" in response[2]
    assert b"id=\"task-modal\"" in response[2]
    assert b"class=\"form-check-input weekday-checkbox\"" in response[2]
    assert b"cdn.jsdelivr.net/npm/bootstrap@5.3.3" in response[2]


def test_dashboard_homepage_inlines_css_and_resolves_relative_actions() -> None:
    server = DashboardServer(StubService())

    response = server.handle_request(
        method="GET",
        raw_path="/",
        remote_addr="127.0.0.1",
    )

    assert response[0] == 200
    assert b"<style>" in response[2]
    assert b".page-header" in response[2]
    assert b"resolveDashboardUrl" in response[2]


def test_dashboard_tasks_endpoint_lists_tasks() -> None:
    server = DashboardServer(StubService())

    response = server.handle_request(
        method="GET",
        raw_path="/api/tasks",
        remote_addr="127.0.0.1",
    )

    assert response[0] == 200
    payload = json.loads(response[2].decode("utf-8"))
    assert payload["tasks"][0]["task_type"] == "auto_check_update"


def test_dashboard_tasks_endpoint_creates_task() -> None:
    service = StubService()
    server = DashboardServer(service)

    response = server.handle_request(
        method="POST",
        raw_path="/api/tasks",
        body=json.dumps(
            {
                "task_type": "auto_update",
                "weekdays": ["mon", "tue"],
                "hour": 3,
                "minute": 15,
                "enabled": True,
            }
        ).encode("utf-8"),
        remote_addr="127.0.0.1",
    )

    assert response[0] == 201
    payload = json.loads(response[2].decode("utf-8"))
    assert payload["status"] == "created"
    assert any(task["task_type"] == "auto_update" for task in payload["tasks"])


def test_dashboard_tasks_endpoint_updates_enabled_state() -> None:
    service = StubService()
    server = DashboardServer(service)

    response = server.handle_request(
        method="POST",
        raw_path="/api/tasks/task-check/enabled",
        body=json.dumps({"enabled": False}).encode("utf-8"),
        remote_addr="127.0.0.1",
    )

    assert response[0] == 200
    payload = json.loads(response[2].decode("utf-8"))
    assert payload["task"]["enabled"] is False


def test_dashboard_scoped_install_action_is_available() -> None:
    service = StubService()
    server = DashboardServer(service)

    response = server.handle_request(
        method="POST",
        raw_path="/api/actions/update/core",
        remote_addr="127.0.0.1",
    )

    assert response[0] == 200
    assert service.queued == [("install", "dashboard", {"allowed_types": ["core"]})]
