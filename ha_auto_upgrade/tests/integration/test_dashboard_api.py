from __future__ import annotations

from ha_autoupgrade.web.server import DashboardServer


class StubConfig:
    webhook_trigger_token = "secret"


class StubService:
    def __init__(self) -> None:
        self.config = StubConfig()
        self.queued: list[tuple[str, str]] = []

    def enqueue_action(self, action: str, source: str = "manual", payload=None) -> None:
        self.queued.append((action, source))

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
    client = server.app.test_client()

    response = client.get("/api/status", environ_base={"REMOTE_ADDR": "127.0.0.1"})

    assert response.status_code == 200


def test_dashboard_webhook_requires_token() -> None:
    service = StubService()
    server = DashboardServer(service)
    client = server.app.test_client()

    unauthorized = client.post("/api/webhook/trigger")
    authorized = client.post("/api/webhook/trigger?token=secret")

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert service.queued == [("install", "webhook")]
