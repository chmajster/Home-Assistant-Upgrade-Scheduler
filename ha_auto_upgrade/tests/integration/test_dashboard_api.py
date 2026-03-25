from __future__ import annotations

from ha_autoupgrade.web.server import DashboardServer


class StubConfig:
    webhook_trigger_token = "secret"


class StubService:
    def __init__(self) -> None:
        self.config = StubConfig()
        self.queued: list[tuple[str, str, object]] = []

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
            "config": {},
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
