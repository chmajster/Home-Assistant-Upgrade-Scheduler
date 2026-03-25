from __future__ import annotations

import logging

import pytest

from ha_autoupgrade.api.supervisor import SupervisorClient


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.headers = {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, url: str, json: dict | None = None, timeout: int = 30):
        self.calls.append((method, url, json))
        if url.endswith("/addons/self/options"):
            return FakeResponse({"result": "ok", "data": {"saved": True}})
        return FakeResponse({"result": "ok", "data": {"ping": True}})


def test_supervisor_client_unwraps_payload_and_posts_options(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    client = SupervisorClient(logging.getLogger("test"))
    fake_session = FakeSession()
    client._session = fake_session

    payload = client.set_addon_options("self", {"dry_run": True})

    assert payload == {"saved": True}
    assert fake_session.calls[0][0] == "POST"
    assert fake_session.calls[0][1].endswith("/addons/self/options")
    assert fake_session.calls[0][2] == {"options": {"dry_run": True}}


def test_wait_for_job_polls_until_done(monkeypatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "token")
    client = SupervisorClient(logging.getLogger("test"))
    jobs = iter([{"done": False}, {"done": True, "reference": "backup-1"}])
    monkeypatch.setattr(client, "job_info", lambda _job_id: next(jobs))

    result = client.wait_for_job("job-1", timeout_seconds=2, poll_seconds=0)

    assert result["reference"] == "backup-1"
