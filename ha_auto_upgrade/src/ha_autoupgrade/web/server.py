"""Ingress dashboard and local API."""

from __future__ import annotations

from html import escape
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ha_autoupgrade.constants import (
    ALLOWED_DASHBOARD_IPS,
    ALLOWED_DASHBOARD_PREFIXES,
    DEFAULT_WEEKDAYS,
    WEB_PORT,
)
from ha_autoupgrade.i18n import STRINGS
from ha_autoupgrade.utils.dates import local_now, parse_iso_datetime


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
        config = status.get("config", {})
        install_days = str(config.get("install_days", "sun") or "sun")
        install_hour = str(config.get("install_hour", "03:00") or "03:00")
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
        schedule_frequency = str(config.get("schedule_install_frequency", "") or "").lower()
        if schedule_frequency not in {"daily", "weekly", "monthly", "once"}:
            schedule_frequency = "daily" if selected_day_set == set(DEFAULT_WEEKDAYS) else "weekly"
        schedule_range_end = str(config.get("schedule_install_time_range_end", "") or "")
        schedule_monthday = int(config.get("schedule_install_monthday", 1) or 1)
        once_at = parse_iso_datetime(str(config.get("schedule_install_once_at", "") or ""))
        once_local = once_at.astimezone() if once_at else None
        once_date = once_local.date().isoformat() if once_local else ""
        once_time = once_local.strftime("%H:%M") if once_local else install_hour
        schedule_time_value = once_time if schedule_frequency == "once" else install_hour
        schedule_mode = "once" if schedule_frequency == "once" else "weekly" if schedule_frequency == "weekly" else "daily"
        schedule_time_label = (
            f"{schedule_time_value}-{schedule_range_end}"
            if schedule_range_end and schedule_frequency != "once"
            else schedule_time_value
        )
        if schedule_frequency == "daily":
            install_schedule_label = f"{ui['schedule_summary_daily']} @ {schedule_time_label}"
        elif schedule_frequency == "monthly":
            install_schedule_label = (
                f"{ui['schedule_summary_monthly']} {schedule_monthday} @ {schedule_time_label}"
            )
        elif schedule_frequency == "once" and once_local:
            install_schedule_label = (
                f"{ui['schedule_summary_once']} {once_local.date().isoformat()} {once_local.strftime('%H:%M')}"
            )
        else:
            install_schedule_label = (
                f"{ui['schedule_summary_weekly']}: "
                f"{', '.join(label for code, label in weekday_order if code in selected_days)} @ {schedule_time_label}"
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
        schedule_frequency_json = json.dumps(schedule_frequency)
        schedule_range_end_json = json.dumps(schedule_range_end)
        local_today_json = json.dumps(local_now().date().isoformat())
        install_day_required_json = json.dumps(ui["install_day_required"])
        install_hour_required_json = json.dumps(ui["install_hour_required"])
        install_range_end_required_json = json.dumps(ui["install_range_end_required"])
        install_month_day_required_json = json.dumps(ui["install_month_day_required"])
        install_once_date_required_json = json.dumps(ui["install_once_date_required"])
        install_once_future_required_json = json.dumps(ui["install_once_future_required"])
        full_day_window_json = json.dumps("00:00-23:59")
        schedule_frequency_once_hint_json = json.dumps(ui["schedule_frequency_once_hint"])
        day_hints_json = json.dumps(
            {
                "daily": ui["schedule_days_hint_daily"],
                "weekly": ui["schedule_days_hint_weekly"],
                "monthly": ui["schedule_days_hint_monthly"],
                "once": ui["schedule_days_hint_once"],
            }
        )

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
          <p>{escape(ui['install_schedule'])}: {escape(install_schedule_label)}</p>
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
            <div class="schedule-header">
              <h4>{escape(ui['schedule_panel_title'])}</h4>
              <p>{escape(ui['schedule_panel_hint'])}</p>
            </div>
            <div class="schedule-section">
              <div class="section-copy">
                <h5>{escape(ui['schedule_mode'])}</h5>
              </div>
              <div class="schedule-choice-group">
                <button
                  type="button"
                  id="mode-daily"
                  class="schedule-choice{' is-selected' if schedule_mode == 'daily' else ''}"
                  onclick="setScheduleMode('daily')"
                >{escape(ui['schedule_mode_daily'])}</button>
                <button
                  type="button"
                  id="mode-weekly"
                  class="schedule-choice{' is-selected' if schedule_mode == 'weekly' else ''}"
                  onclick="setScheduleMode('weekly')"
                >{escape(ui['schedule_mode_weekly'])}</button>
                <button
                  type="button"
                  id="mode-once"
                  class="schedule-choice{' is-selected' if schedule_mode == 'once' else ''}"
                  onclick="setScheduleMode('once')"
                >{escape(ui['schedule_mode_once'])}</button>
              </div>
            </div>
            <div class="schedule-section">
              <div class="section-copy">
                <h5>{escape(ui['schedule_days'])}</h5>
                <p id="schedule-days-hint"></p>
              </div>
              <div id="weekly-day-picker" class="day-toggle-group"{' hidden' if schedule_frequency != 'weekly' else ''}>{day_buttons}</div>
              <div id="monthly-day-field" class="field-group"{' hidden' if schedule_frequency != 'monthly' else ''}>
                <label for="schedule-monthday">{escape(ui['schedule_month_day'])}</label>
                <input id="schedule-monthday" type="number" min="1" max="31" value="{schedule_monthday}">
              </div>
              <div id="once-date-field" class="field-group"{' hidden' if schedule_frequency != 'once' else ''}>
                <label for="schedule-once-date">{escape(ui['schedule_once_date'])}</label>
                <input id="schedule-once-date" type="date" value="{escape(once_date)}">
              </div>
            </div>
            <div class="schedule-section">
              <div class="section-copy">
                <h5>{escape(ui['schedule_time'])}</h5>
                <p>{escape(ui['schedule_time_hint'])}</p>
              </div>
              <div class="schedule-choice-group compact">
                <button type="button" id="time-mode-point" class="schedule-choice" onclick="setTimeMode(false)">{escape(ui['schedule_exact_time'])}</button>
                <button type="button" id="time-mode-range" class="schedule-choice" onclick="setTimeMode(true)">{escape(ui['schedule_time_range'])}</button>
              </div>
              <div class="schedule-controls">
                <div class="field-group">
                  <label for="install-hour">{escape(ui['install_time'])}</label>
                  <input id="install-hour" type="time" value="{escape(schedule_time_value)}">
                </div>
                <div id="schedule-end-field" class="field-group"{' hidden' if not schedule_range_end or schedule_frequency == 'once' else ''}>
                  <label for="schedule-end-time">{escape(ui['schedule_window_end'])}</label>
                  <input id="schedule-end-time" type="time" value="{escape(schedule_range_end)}">
                </div>
              </div>
            </div>
            <div class="schedule-section">
              <div class="section-copy">
                <h5>{escape(ui['schedule_frequency'])}</h5>
                <p id="schedule-frequency-hint"></p>
              </div>
              <div class="schedule-choice-group">
                <button type="button" id="frequency-daily" class="schedule-choice" onclick="setScheduleFrequency('daily')">{escape(ui['schedule_frequency_daily'])}</button>
                <button type="button" id="frequency-weekly" class="schedule-choice" onclick="setScheduleFrequency('weekly')">{escape(ui['schedule_frequency_weekly'])}</button>
                <button type="button" id="frequency-monthly" class="schedule-choice" onclick="setScheduleFrequency('monthly')">{escape(ui['schedule_frequency_monthly'])}</button>
              </div>
            </div>
            <div class="schedule-actions">
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
      const scheduleDayHints = {day_hints_json};
      const scheduleState = {{
        frequency: {schedule_frequency_json},
        selectedDays: new Set({selected_days_json}),
        useRange: Boolean({schedule_range_end_json}) && {schedule_frequency_json} !== 'once'
      }};
      function activeScheduleMode() {{
        if (scheduleState.frequency === 'once') {{
          return 'once';
        }}
        if (scheduleState.frequency === 'weekly') {{
          return 'weekly';
        }}
        return 'daily';
      }}
      function renderChoiceState(id, active) {{
        const element = document.getElementById(id);
        if (!element) {{
          return;
        }}
        element.classList.toggle('is-selected', active);
        element.setAttribute('aria-pressed', active ? 'true' : 'false');
      }}
      function syncDayButtons() {{
        document.querySelectorAll('.day-chip').forEach((button) => {{
          const day = button.dataset.day;
          const selected = scheduleState.selectedDays.has(day);
          button.classList.toggle('is-selected', selected);
          button.setAttribute('aria-pressed', selected ? 'true' : 'false');
        }});
      }}
      function renderScheduleControls() {{
        const mode = activeScheduleMode();
        const isOnce = scheduleState.frequency === 'once';
        renderChoiceState('mode-daily', mode === 'daily');
        renderChoiceState('mode-weekly', mode === 'weekly');
        renderChoiceState('mode-once', mode === 'once');
        renderChoiceState('frequency-daily', scheduleState.frequency === 'daily');
        renderChoiceState('frequency-weekly', scheduleState.frequency === 'weekly');
        renderChoiceState('frequency-monthly', scheduleState.frequency === 'monthly');
        renderChoiceState('time-mode-point', !scheduleState.useRange || isOnce);
        renderChoiceState('time-mode-range', scheduleState.useRange && !isOnce);
        document.getElementById('weekly-day-picker').hidden = scheduleState.frequency !== 'weekly';
        document.getElementById('monthly-day-field').hidden = scheduleState.frequency !== 'monthly';
        document.getElementById('once-date-field').hidden = !isOnce;
        document.getElementById('schedule-end-field').hidden = !scheduleState.useRange || isOnce;
        document.getElementById('schedule-days-hint').textContent = scheduleDayHints[scheduleState.frequency];
        document.getElementById('schedule-frequency-hint').textContent = isOnce ? {schedule_frequency_once_hint_json} : '';
        ['frequency-daily', 'frequency-weekly', 'frequency-monthly'].forEach((id) => {{
          document.getElementById(id).disabled = isOnce;
        }});
        ['time-mode-point', 'time-mode-range'].forEach((id) => {{
          document.getElementById(id).disabled = isOnce;
        }});
        document.getElementById('schedule-once-date').min = {local_today_json};
        syncDayButtons();
      }}
      function setScheduleMode(mode) {{
        if (mode === 'once') {{
          scheduleState.frequency = 'once';
          scheduleState.useRange = false;
        }} else if (mode === 'weekly') {{
          scheduleState.frequency = 'weekly';
        }} else {{
          scheduleState.frequency = 'daily';
        }}
        renderScheduleControls();
      }}
      function setScheduleFrequency(frequency) {{
        scheduleState.frequency = frequency;
        renderScheduleControls();
      }}
      function setTimeMode(useRange) {{
        scheduleState.useRange = useRange;
        renderScheduleControls();
      }}
      function toggleInstallDay(day, _element) {{
        if (scheduleState.selectedDays.has(day)) {{
          scheduleState.selectedDays.delete(day);
        }} else {{
          scheduleState.selectedDays.add(day);
        }}
        syncDayButtons();
      }}
      async function saveInstallSchedule() {{
        const installHour = document.getElementById('install-hour').value;
        if (!installHour) {{
          document.getElementById('action-result').textContent = {install_hour_required_json};
          return;
        }}
        if (scheduleState.frequency === 'weekly' && !scheduleState.selectedDays.size) {{
          document.getElementById('action-result').textContent = {install_day_required_json};
          return;
        }}
        const rangeEnd = document.getElementById('schedule-end-time').value;
        if (scheduleState.useRange && scheduleState.frequency !== 'once' && !rangeEnd) {{
          document.getElementById('action-result').textContent = {install_range_end_required_json};
          return;
        }}
        const monthDay = Number.parseInt(document.getElementById('schedule-monthday').value || '0', 10);
        if (scheduleState.frequency === 'monthly' && (!Number.isInteger(monthDay) || monthDay < 1 || monthDay > 31)) {{
          document.getElementById('action-result').textContent = {install_month_day_required_json};
          return;
        }}
        const onceDate = document.getElementById('schedule-once-date').value;
        let onceAt = '';
        if (scheduleState.frequency === 'once') {{
          if (!onceDate) {{
            document.getElementById('action-result').textContent = {install_once_date_required_json};
            return;
          }}
          const localDateTime = new Date(`${{onceDate}}T${{installHour}}:00`);
          if (Number.isNaN(localDateTime.getTime()) || localDateTime <= new Date()) {{
            document.getElementById('action-result').textContent = {install_once_future_required_json};
            return;
          }}
          onceAt = localDateTime.toISOString();
        }}
        const orderedDays = installWeekdayOrder.filter((day) => scheduleState.selectedDays.has(day));
        let installDays = orderedDays.join(',');
        let allowedWeekdays = orderedDays;
        if (scheduleState.frequency === 'daily' || scheduleState.frequency === 'monthly') {{
          installDays = installWeekdayOrder.join(',');
          allowedWeekdays = installWeekdayOrder;
        }}
        if (scheduleState.frequency === 'once') {{
          const onceRun = new Date(`${{onceDate}}T12:00:00`);
          installDays = installWeekdayOrder[(onceRun.getDay() + 6) % 7];
          allowedWeekdays = installWeekdayOrder;
        }}
        const maintenanceWindow = scheduleState.useRange && scheduleState.frequency !== 'once'
          ? `${{installHour}}-${{rangeEnd}}`
          : {full_day_window_json};
        await postAction('/api/actions/import', {{
          options: {{
            install_days: installDays,
            install_hour: installHour,
            maintenance_window: maintenanceWindow,
            schedule_allowed_weekdays: allowedWeekdays,
            schedule_install_cron: '',
            schedule_install_frequency: scheduleState.frequency,
            schedule_install_monthday: scheduleState.frequency === 'monthly' ? monthDay : 1,
            schedule_install_once_at: onceAt,
            schedule_install_time_range_end: scheduleState.useRange && scheduleState.frequency !== 'once' ? rangeEnd : ''
          }}
        }});
      }}
      renderScheduleControls();
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
