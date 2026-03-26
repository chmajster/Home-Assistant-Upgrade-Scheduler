from __future__ import annotations

import json
import logging
from urllib import error, request

from ha_autoupgrade.api.supervisor import SupervisorAPIError, SupervisorClient


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_supervisor_client_initializes_headers_with_slots(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")

    client = SupervisorClient(logging.getLogger("test"))

    assert client._headers["Authorization"] == "Bearer token"
    assert client._headers["Content-Type"] == "application/json"


def test_supervisor_client_unwraps_payload_and_posts_options(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    client = SupervisorClient(logging.getLogger("test"))
    calls: list[tuple[str, str, bytes | None]] = []

    def fake_open(self, req: request.Request):
        calls.append((req.get_method(), req.full_url, req.data))
        if req.full_url.endswith("/addons/self/options"):
            return FakeResponse({"result": "ok", "data": {"saved": True}})
        return FakeResponse({"result": "ok", "data": {"ping": True}})

    monkeypatch.setattr(SupervisorClient, "_open", fake_open)

    payload = client.set_addon_options("self", {"dry_run": True})

    assert payload == {"saved": True}
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/addons/self/options")
    assert json.loads((calls[0][2] or b"{}").decode("utf-8")) == {"options": {"dry_run": True}}


def test_wait_for_job_polls_until_done(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    client = SupervisorClient(logging.getLogger("test"))
    jobs = iter([{"done": False}, {"done": True, "reference": "backup-1"}])
    monkeypatch.setattr(SupervisorClient, "job_info", lambda self, _job_id: next(jobs))

    result = client.wait_for_job("job-1", timeout_seconds=2, poll_seconds=0)

    assert result["reference"] == "backup-1"


def test_refresh_updates_uses_addon_safe_endpoint_first(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    client = SupervisorClient(logging.getLogger("test"))
    calls: list[tuple[str, str]] = []

    def fake_request(self, method: str, path: str, **_kwargs):
        calls.append((method, path))
        return {}

    monkeypatch.setattr(SupervisorClient, "_request", fake_request)

    client.refresh_updates()

    assert calls == [("POST", "/refresh_updates")]


def test_refresh_updates_falls_back_when_refresh_endpoints_are_restricted(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    client = SupervisorClient(logging.getLogger("test"))
    calls: list[tuple[str, str]] = []

    def http_error(path: str, status: int) -> error.HTTPError:
        return error.HTTPError(f"http://supervisor{path}", status, "error", hdrs=None, fp=None)

    def fake_request(self, method: str, path: str, **_kwargs):
        calls.append((method, path))
        if path == "/refresh_updates":
            raise SupervisorAPIError("POST /refresh_updates failed") from http_error(path, 404)
        if path == "/reload_updates":
            raise SupervisorAPIError("POST /reload_updates failed") from http_error(path, 403)
        return {}

    monkeypatch.setattr(SupervisorClient, "_request", fake_request)

    client.refresh_updates()

    assert calls == [
        ("POST", "/refresh_updates"),
        ("POST", "/reload_updates"),
        ("POST", "/store/reload"),
    ]
