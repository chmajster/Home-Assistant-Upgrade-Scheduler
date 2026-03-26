"""Ingress dashboard and local API."""

from __future__ import annotations

from html import escape
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ha_autoupgrade.constants import ALLOWED_DASHBOARD_IPS, ALLOWED_DASHBOARD_PREFIXES, WEB_PORT
from ha_autoupgrade.i18n import STRINGS


class DashboardServer:
    def __init__(self, service) -> None:
        self.service = service
        self.logger = logging.getLogger("ha_autoupgrade.web")
        self.translations = STRINGS
        self.static_root = Path(__file__).resolve().parent / "static"

    def _language(self, query: dict[str, list[str]], accept_language: str) -> str:
        requested = (query.get("lang") or [""])[0]
        if requested in self.translations:
            return requested
        if accept_language.lower().startswith("pl"):
            return "pl"
        return "en"

    def _is_allowed(self, path: str, remote_addr: str) -> bool:
        if path.startswith("/api/webhook/trigger") or path.startswith("/static/"):
            return True
        if remote_addr in ALLOWED_DASHBOARD_IPS:
            return True
        return any(remote_addr.startswith(prefix) for prefix in ALLOWED_DASHBOARD_PREFIXES)

    def _json(self, status: int, payload: Any) -> tuple[int, str, bytes]:
        return (status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))

    def _text(self, status: int, payload: str, content_type: str) -> tuple[int, str, bytes]:
        return (status, content_type, payload.encode("utf-8"))

    def _render_dashboard(self, language: str) -> str:
        ui = self.translations.get(language, self.translations["en"])["ui"]
        status = self.service.status()
        health = self.service.health()
        state = status["state"]
        pending_rows = "".join(
            (
                "<tr>"
                f"<td>{escape(item['name'])} <span class=\"pill\">{escape(item['component_type'])}</span></td>"
                f"<td>{escape(item['current_version'])}</td>"
                f"<td>{escape(item['target_version'])}</td>"
                "</tr>"
            )
            for item in state.get("pending_updates", [])
        ) or f"<tr><td colspan=\"3\">{escape(ui['no_updates'])}</td></tr>"

        history_rows = "".join(
            (
                "<li>"
                f"<span class=\"timeline-event\">{escape(item.get('event', 'event'))}</span>"
                f"<span class=\"timeline-time\">{escape(item.get('ts', ''))}</span>"
                "</li>"
            )
            for item in status.get("recent_history", [])
        ) or f"<li>{escape(ui['no_history'])}</li>"

        log_rows = "".join(
            (
                f"<div class=\"log-line log-{escape(item.get('level', 'info'))}\">"
                f"<span>{escape(item.get('timestamp', ''))}</span>"
                f"<strong>{escape(item.get('level', 'info'))}</strong>"
                f"<code>{escape(item.get('message', ''))}</code>"
                "</div>"
            )
            for item in status.get("recent_logs", [])
        ) or f"<p>{escape(ui['no_logs'])}</p>"

        skip_rows = "".join(
            f"<li>{escape(reason)}</li>"
            for reason in (state.get("last_run") or {}).get("skipped_reasons", [])
        ) or f"<li>{escape(ui['no_skips'])}</li>"

        exclusion_rows = "".join(
            f"<li>{escape(slug)}</li>" for slug in status.get("config", {}).get("excluded_addons", [])
        ) or f"<li>{escape(ui['no_exclusions'])}</li>"

        last_check = (state.get("last_check") or {}).get("checked_at", "n/a")
        last_run_status = (state.get("last_run") or {}).get("status", "n/a")
        health_label = ui["ok"] if health.get("ok") else ui["attention"]
        health_class = "ok" if health.get("ok") else "bad"
        ha_state = health.get("snapshot", {}).get("ha_state", "unknown")
        safe_mode_until = state.get("safe_mode_until") or "off"
        last_backup = state.get("last_backup") or "n/a"
        next_install = state.get("next_install") or "n/a"
        install_days = str(status.get("config", {}).get("install_days", "sun") or "sun")
        install_hour = str(status.get("config", {}).get("install_hour", "03:00") or "03:00")
        weekday_order = [
            ("mon", ui["day_mon"]),
            ("tue", ui["day_tue"]),
            ("wed", ui["day_wed"]),
            ("thu", ui["day_thu"]),
            ("fri", ui["day_fri"]),
            ("sat", ui["day_sat"]),
            ("sun", ui["day_sun"]),
        ]
        selected_day_set = {token.strip().lower() for token in install_days.split(",") if token.strip()}
        selected_days = [code for code, _label in weekday_order if code in selected_day_set] or ["sun"]
        install_schedule_label = ", ".join(
            label for code, label in weekday_order if code in selected_days
        )
        day_buttons = "".join(
            (
                f"<button type=\"button\" class=\"day-chip{' is-selected' if code in selected_days else ''}\" "
                f"data-day=\"{code}\" aria-pressed=\"{'true' if code in selected_days else 'false'}\" "
                f"onclick=\"toggleInstallDay('{code}', this)\">{escape(label)}</button>"
            )
            for code, label in weekday_order
        )
        weekday_codes_json = json.dumps([code for code, _label in weekday_order])
        selected_days_json = json.dumps(selected_days)
        install_day_required_json = json.dumps(ui["install_day_required"])
        install_hour_required_json = json.dumps(ui["install_hour_required"])

        return f"""<!doctype html>
<html lang="{escape(language)}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(ui['title'])}</title>
    <link rel="stylesheet" href="/static/dashboard.css">
  </head>
  <body>
    <div class="background-orb orb-a"></div>
    <div class="background-orb orb-b"></div>
    <main class="layout">
      <section class="hero">
        <div>
          <p class="eyebrow">{escape(ui['eyebrow'])}</p>
          <h1>{escape(ui['title'])}</h1>
          <p class="lead">{escape(ui['subtitle'])}</p>
        </div>
        <div class="hero-actions">
          <button onclick="postAction('/api/actions/check')">{escape(ui['check_now'])}</button>
          <button class="accent" onclick="postAction('/api/actions/update')">{escape(ui['update_now'])}</button>
          <button class="accent" onclick="postAction('/api/actions/check-install')">{escape(ui['check_install_now'])}</button>
        </div>
      </section>
      <section class="card-grid">
        <article class="card metric-card">
          <p class="metric-label">{escape(ui['health'])}</p>
          <h2 class="{health_class}">{escape(health_label)}</h2>
          <p>{escape(str(ha_state))}</p>
        </article>
        <article class="card metric-card">
          <p class="metric-label">{escape(ui['pending_updates'])}</p>
          <h2>{len(state.get('pending_updates', []))}</h2>
          <p>{escape(ui['last_check'])}: {escape(str(last_check))}</p>
        </article>
        <article class="card metric-card">
          <p class="metric-label">{escape(ui['next_install'])}</p>
          <h2>{escape(str(next_install))}</h2>
          <p>{escape(ui['install_schedule'])}: {escape(f"{install_schedule_label} @ {install_hour}")}</p>
          <p>{escape(ui['safe_mode'])}: {escape(str(safe_mode_until))}</p>
        </article>
        <article class="card metric-card">
          <p class="metric-label">{escape(ui['last_backup'])}</p>
          <h2>{escape(str(last_backup))}</h2>
          <p>{escape(ui['last_result'])}: {escape(str(last_run_status))}</p>
        </article>
      </section>
      <section class="content-grid">
        <article class="card">
          <div class="card-header">
            <h3>{escape(ui['actions'])}</h3>
            <p>{escape(ui['actions_hint'])}</p>
          </div>
          <div class="action-grid">
            <button class="accent" onclick="postAction('/api/actions/update/core')">{escape(ui['update_core_now'])}</button>
            <button class="accent" onclick="postAction('/api/actions/update/supervisor')">{escape(ui['update_supervisor_now'])}</button>
            <button class="accent" onclick="postAction('/api/actions/update/os')">{escape(ui['update_os_now'])}</button>
            <button class="accent" onclick="postAction('/api/actions/update/addons')">{escape(ui['update_addons_now'])}</button>
            <button onclick="postAction('/api/actions/backup')">{escape(ui['backup_now'])}</button>
            <button onclick="postAction('/api/actions/retry')">{escape(ui['retry_failed'])}</button>
            <button onclick="postAction('/api/actions/clear')">{escape(ui['clear_stuck'])}</button>
            <button onclick="postAction('/api/actions/export')">{escape(ui['export_diag'])}</button>
            <button onclick="postAction('/api/actions/self-test')">{escape(ui['self_test'])}</button>
          </div>
          <div class="schedule-box">
            <h4>{escape(ui['install_days_editor'])}</h4>
            <p>{escape(ui['install_days_hint'])}</p>
            <div class="day-toggle-group">{day_buttons}</div>
            <div class="schedule-controls">
              <div class="field-group">
                <label for="install-hour">{escape(ui['install_time'])}</label>
                <input id="install-hour" type="time" value="{escape(install_hour)}">
              </div>
              <button class="accent" onclick="saveInstallSchedule()">{escape(ui['save_install_schedule'])}</button>
            </div>
          </div>
          <div class="import-box">
            <label for="import-options">{escape(ui['import_config'])}</label>
            <textarea id="import-options" rows="8" placeholder='{{"log_level":"debug"}}'></textarea>
            <button class="accent" onclick="importOptions()">{escape(ui['import_apply'])}</button>
          </div>
          <p id="action-result" class="result-note"></p>
          <div class="detail-grid">
            <div>
              <h4>{escape(ui['skipped_reasons'])}</h4>
              <ul class="mini-list">{skip_rows}</ul>
            </div>
            <div>
              <h4>{escape(ui['exclusions'])}</h4>
              <ul class="mini-list">{exclusion_rows}</ul>
            </div>
          </div>
        </article>
        <article class="card">
          <div class="card-header">
            <h3>{escape(ui['pending_updates'])}</h3>
            <p>{escape(ui['policy_note'])}</p>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{escape(ui['component'])}</th>
                  <th>{escape(ui['current_version'])}</th>
                  <th>{escape(ui['target_version'])}</th>
                </tr>
              </thead>
              <tbody>{pending_rows}</tbody>
            </table>
          </div>
        </article>
        <article class="card">
          <div class="card-header">
            <h3>{escape(ui['audit_trail'])}</h3>
            <p>{escape(ui['audit_hint'])}</p>
          </div>
          <ul class="timeline">{history_rows}</ul>
        </article>
        <article class="card log-card">
          <div class="card-header">
            <h3>{escape(ui['recent_logs'])}</h3>
            <p>{escape(ui['logs_hint'])}</p>
          </div>
          <div class="log-list">{log_rows}</div>
        </article>
      </section>
    </main>
    <script>
      async function postAction(url, body = null) {{
        const response = await fetch(url, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: body ? JSON.stringify(body) : null
        }});
        const result = await response.json();
        document.getElementById('action-result').textContent = JSON.stringify(result, null, 2);
        setTimeout(() => window.location.reload(), 1500);
      }}
      const installWeekdayOrder = {weekday_codes_json};
      const selectedInstallDays = new Set({selected_days_json});
      function toggleInstallDay(day, element) {{
        if (selectedInstallDays.has(day)) {{
          selectedInstallDays.delete(day);
        }} else {{
          selectedInstallDays.add(day);
        }}
        const isSelected = selectedInstallDays.has(day);
        element.classList.toggle('is-selected', isSelected);
        element.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      }}
      async function saveInstallSchedule() {{
        if (!selectedInstallDays.size) {{
          document.getElementById('action-result').textContent = {install_day_required_json};
          return;
        }}
        const installHour = document.getElementById('install-hour').value;
        if (!installHour) {{
          document.getElementById('action-result').textContent = {install_hour_required_json};
          return;
        }}
        const orderedDays = installWeekdayOrder.filter((day) => selectedInstallDays.has(day));
        await postAction('/api/actions/import', {{
          options: {{
            install_days: orderedDays.join(','),
            install_hour: installHour
          }}
        }});
      }}
      async function importOptions() {{
        const raw = document.getElementById('import-options').value.trim();
        if (!raw) {{
          document.getElementById('action-result').textContent = 'No JSON provided.';
          return;
        }}
        let parsed;
        try {{
          parsed = JSON.parse(raw);
        }} catch (_error) {{
          document.getElementById('action-result').textContent = 'Invalid JSON payload.';
          return;
        }}
        await postAction('/api/actions/import', {{ options: parsed }});
      }}
    </script>
  </body>
</html>"""

    def handle_request(
        self,
        *,
        method: str,
        raw_path: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        remote_addr: str = "127.0.0.1",
    ) -> tuple[int, str, bytes]:
        headers = headers or {}
        parsed = urlparse(raw_path)
        query = parse_qs(parsed.query)
        if not self._is_allowed(parsed.path, remote_addr):
            return self._text(403, "Forbidden", "text/plain; charset=utf-8")

        if method == "GET" and parsed.path == "/":
            language = self._language(query, headers.get("Accept-Language", ""))
            return self._text(200, self._render_dashboard(language), "text/html; charset=utf-8")
        if method == "GET" and parsed.path == "/api/status":
            return self._json(200, self.service.status())
        if method == "GET" and parsed.path == "/api/health":
            return self._json(200, self.service.health())
        if method == "GET" and parsed.path == "/api/history":
            return self._json(200, self.service.status()["recent_history"])
        if method == "GET" and parsed.path == "/static/dashboard.css":
            css = (self.static_root / "dashboard.css").read_text(encoding="utf-8")
            return self._text(200, css, "text/css; charset=utf-8")

        if method == "POST" and parsed.path == "/api/actions/check":
            self.service.enqueue_action("check", "dashboard")
            return self._json(200, {"status": "queued", "action": "check"})
        if method == "POST" and parsed.path == "/api/actions/check-install":
            self.service.enqueue_action("check_install", "dashboard")
            return self._json(200, {"status": "queued", "action": "check_install"})
        if method == "POST" and parsed.path == "/api/actions/update":
            self.service.enqueue_action("install", "dashboard")
            return self._json(200, {"status": "queued", "action": "install"})
        if method == "POST" and parsed.path == "/api/actions/update/core":
            self.service.enqueue_action("install", "dashboard", {"allowed_types": ["core"]})
            return self._json(200, {"status": "queued", "action": "install", "allowed_types": ["core"]})
        if method == "POST" and parsed.path == "/api/actions/update/supervisor":
            self.service.enqueue_action("install", "dashboard", {"allowed_types": ["supervisor"]})
            return self._json(200, {"status": "queued", "action": "install", "allowed_types": ["supervisor"]})
        if method == "POST" and parsed.path == "/api/actions/update/os":
            self.service.enqueue_action("install", "dashboard", {"allowed_types": ["os"]})
            return self._json(200, {"status": "queued", "action": "install", "allowed_types": ["os"]})
        if method == "POST" and parsed.path == "/api/actions/update/addons":
            self.service.enqueue_action("install", "dashboard", {"allowed_types": ["addon"]})
            return self._json(200, {"status": "queued", "action": "install", "allowed_types": ["addon"]})
        if method == "POST" and parsed.path == "/api/actions/backup":
            self.service.enqueue_action("backup", "dashboard")
            return self._json(200, {"status": "queued", "action": "backup"})
        if method == "POST" and parsed.path == "/api/actions/retry":
            self.service.enqueue_action("retry", "dashboard")
            return self._json(200, {"status": "queued", "action": "retry"})
        if method == "POST" and parsed.path == "/api/actions/clear":
            self.service.enqueue_action("clear", "dashboard")
            return self._json(200, {"status": "queued", "action": "clear"})
        if method == "POST" and parsed.path == "/api/actions/export":
            return self._json(200, self.service.export_diagnostics())
        if method == "POST" and parsed.path == "/api/actions/self-test":
            return self._json(200, self.service.self_test())
        if method == "POST" and parsed.path == "/api/actions/import":
            payload = json.loads(body.decode("utf-8") or "{}")
            return self._json(200, self.service.import_configuration(payload))
        if method == "POST" and parsed.path == "/api/webhook/trigger":
            configured = self.service.config.webhook_trigger_token
            provided = (query.get("token") or [""])[0]
            auth_header = headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                provided = auth_header[7:]
            if configured and provided != configured:
                return self._text(401, "Unauthorized", "text/plain; charset=utf-8")
            self.service.enqueue_action("install", "webhook")
            return self._json(200, {"status": "queued", "action": "install"})

        return self._text(404, "Not found", "text/plain; charset=utf-8")

    def run(self) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                status, content_type, payload = server.handle_request(
                    method="GET",
                    raw_path=self.path,
                    headers={key: value for key, value in self.headers.items()},
                    remote_addr=self.client_address[0],
                )
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                status, content_type, payload = server.handle_request(
                    method="POST",
                    raw_path=self.path,
                    body=body,
                    headers={key: value for key, value in self.headers.items()},
                    remote_addr=self.client_address[0],
                )
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                server.logger.debug("%s - %s", self.address_string(), format % args)

        httpd = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), Handler)
        httpd.serve_forever()
