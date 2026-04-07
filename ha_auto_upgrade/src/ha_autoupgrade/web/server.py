"""Ingress dashboard and local API."""

from __future__ import annotations

from html import escape
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ha_autoupgrade.constants import (
    ALLOWED_DASHBOARD_IPS,
    ALLOWED_DASHBOARD_PREFIXES,
    WEB_PORT,
)
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

    def _decode_json_body(self, body: bytes) -> dict[str, Any]:
        if not body:
            return {}
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as err:
            raise ValueError("Invalid JSON payload") from err
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object")
        return payload

    def _dashboard_css(self) -> str:
        css_path = self.static_root / "dashboard.css"
        try:
            return css_path.read_text(encoding="utf-8")
        except OSError:
            self.logger.exception("Failed to read dashboard CSS from %s", css_path)
            return ""

    def _render_dashboard(self, language: str) -> str:
        ui = self.translations.get(language, self.translations["en"])["ui"]
        status = self.service.status()
        health = self.service.health()
        dashboard_css = self._dashboard_css()
        state = status["state"]
        scheduled_tasks = status.get("scheduled_tasks", [])
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
        weekday_order = [
            ("mon", ui["day_mon"]),
            ("tue", ui["day_tue"]),
            ("wed", ui["day_wed"]),
            ("thu", ui["day_thu"]),
            ("fri", ui["day_fri"]),
            ("sat", ui["day_sat"]),
            ("sun", ui["day_sun"]),
        ]
        schedule_summary_fallback = (
          f"{ui.get('schedule_summary_weekly', 'Selected weekdays')} @ {next_install}"
          if next_install != "n/a"
          else ui.get("schedule_panel_hint", "Scheduled automation")
        )
        install_schedule_label = schedule_summary_fallback
        task_title = ui.get("task_section_title", "Harmonogram zadan" if language == "pl" else "Tasks")
        task_hint = ui.get(
          "task_section_hint",
          "Tworz i zarzadzaj zadaniami Auto Update i Auto Check Update"
          if language == "pl"
          else "Create and manage Auto Update and Auto Check Update tasks",
        )
        create_label = ui.get("task_create", "Utworz" if language == "pl" else "Create")
        edit_label = ui.get("task_edit", "Edytuj" if language == "pl" else "Edit")
        enabled_label = ui.get("task_enabled", "Wlaczone" if language == "pl" else "Enabled")
        task_name_label = ui.get("task_name", "Nazwa zadania" if language == "pl" else "Task name")
        task_category_label = ui.get("task_category", "Kategoria" if language == "pl" else "Category")
        task_action_label = ui.get("task_action", "Akcja" if language == "pl" else "Action")
        task_next_run_label = ui.get(
          "task_next_run",
          "Czas nastepnego uruchomienia" if language == "pl" else "Next run",
        )
        task_owner_label = ui.get("task_owner", "Wlasciciel" if language == "pl" else "Owner")
        task_type_label = ui.get("task_type", "Typ zadania" if language == "pl" else "Task type")
        task_days_label = ui.get("task_weekdays", "Dni tygodnia" if language == "pl" else "Weekdays")
        task_hour_label = ui.get("task_hour", "Godzina" if language == "pl" else "Hour")
        task_minute_label = ui.get("task_minute", "Minuta" if language == "pl" else "Minute")
        save_label = ui.get("task_save", "Zapisz" if language == "pl" else "Save")
        cancel_label = ui.get("task_cancel", "Anuluj" if language == "pl" else "Cancel")
        no_tasks_label = ui.get(
          "task_no_entries",
          "Brak zadan harmonogramu" if language == "pl" else "No scheduled tasks",
        )
        validation_days_label = ui.get(
          "task_validation_days",
          "Wybierz co najmniej jeden dzien tygodnia"
          if language == "pl"
          else "Select at least one weekday",
        )
        created_success_label = ui.get(
          "task_created",
          "Zadanie zostalo zapisane" if language == "pl" else "Task saved",
        )
        updated_success_label = ui.get(
          "task_updated",
          "Zadanie zostalo zaktualizowane" if language == "pl" else "Task updated",
        )
        enabled_success_label = ui.get(
          "task_enabled_updated",
          "Stan zadania zostal zmieniony" if language == "pl" else "Task state updated",
        )
        modal_create_title = ui.get(
          "task_modal_create_title",
          "Utworz zadanie harmonogramu" if language == "pl" else "Create scheduled task",
        )
        modal_edit_title = ui.get(
          "task_modal_edit_title",
          "Edytuj zadanie harmonogramu" if language == "pl" else "Edit scheduled task",
        )
        task_type_options = [
          {
            "value": "auto_update",
            "label": ui.get("task_type_auto_update", "Auto Update"),
          },
          {
            "value": "auto_check_update",
            "label": ui.get("task_type_auto_check_update", "Auto Check Update"),
          },
        ]
        task_type_options_html = "".join(
          f"<option value=\"{escape(entry['value'])}\">{escape(entry['label'])}</option>"
          for entry in task_type_options
        )
        weekday_checkboxes = "".join(
          (
            "<div class=\"col-6 col-sm-4 col-md-3\">"
            "<div class=\"form-check\">"
            f"<input class=\"form-check-input weekday-checkbox\" type=\"checkbox\" value=\"{code}\" id=\"weekday-{code}\">"
            f"<label class=\"form-check-label\" for=\"weekday-{code}\">{escape(label)}</label>"
            "</div>"
            "</div>"
          )
          for code, label in weekday_order
        )
        hour_options = "".join(
          f"<option value=\"{hour:02d}\">{hour:02d}</option>" for hour in range(24)
        )
        minute_options = (
          "<option value=\"\">--</option>"
          + "".join(f"<option value=\"{minute:02d}\">{minute:02d}</option>" for minute in range(60))
        )
        weekday_order_json = json.dumps([code for code, _label in weekday_order])
        weekday_labels_json = json.dumps({code: label for code, label in weekday_order})
        task_data_json = json.dumps(scheduled_tasks)
        task_ui_json = json.dumps(
          {
            "noTasks": no_tasks_label,
            "validationDays": validation_days_label,
            "created": created_success_label,
            "updated": updated_success_label,
            "enabledUpdated": enabled_success_label,
            "createTitle": modal_create_title,
            "editTitle": modal_edit_title,
            "edit": edit_label,
            "unknownError": "Wystapil blad" if language == "pl" else "Unexpected error",
          }
        )
        advanced_actions_label = "Akcje zaawansowane" if language == "pl" else "Advanced actions"

        return f"""<!doctype html>
<html lang="{escape(language)}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(ui['title'])}</title>
      <link
        rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
      >
    <style>
{dashboard_css}
    </style>
  </head>
  <body>
    <main class="layout">
      <header class="page-header card">
        <div class="header-main">
          <p class="eyebrow">{escape(ui['eyebrow'])}</p>
          <h1>{escape(ui['title'])}</h1>
          <p class="lead">{escape(ui['subtitle'])}</p>
        </div>
        <div class="button-row primary-actions">
          <button onclick="postAction('/api/actions/check')">{escape(ui['check_now'])}</button>
          <button class="accent" onclick="postAction('/api/actions/check-install')">{escape(ui['check_install_now'])}</button>
          <button class="accent" onclick="postAction('/api/actions/update')">{escape(ui['update_now'])}</button>
        </div>
      </header>
      <section class="status-grid">
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
          <div class="button-row quick-actions">
            <button onclick="postAction('/api/actions/backup')">{escape(ui['backup_now'])}</button>
            <button onclick="postAction('/api/actions/retry')">{escape(ui['retry_failed'])}</button>
            <button onclick="postAction('/api/actions/clear')">{escape(ui['clear_stuck'])}</button>
          </div>
          <details class="section-toggle">
            <summary>{escape(advanced_actions_label)}</summary>
            <div class="toggle-body">
              <div class="action-grid">
                <button class="accent" onclick="postAction('/api/actions/update/core')">{escape(ui['update_core_now'])}</button>
                <button class="accent" onclick="postAction('/api/actions/update/supervisor')">{escape(ui['update_supervisor_now'])}</button>
                <button class="accent" onclick="postAction('/api/actions/update/os')">{escape(ui['update_os_now'])}</button>
                <button class="accent" onclick="postAction('/api/actions/update/addons')">{escape(ui['update_addons_now'])}</button>
                <button onclick="postAction('/api/actions/export')">{escape(ui['export_diag'])}</button>
                <button onclick="postAction('/api/actions/self-test')">{escape(ui['self_test'])}</button>
              </div>
            </div>
          </details>
          <section class="task-manager card mb-0">
            <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
              <div>
                <h3 class="mb-1">{escape(task_title)}</h3>
                <p class="mb-0">{escape(task_hint)}</p>
              </div>
              <button id="create-task-btn" type="button" class="btn btn-primary">{escape(create_label)}</button>
            </div>
            <div class="table-wrap mt-3">
              <table class="table table-dark table-hover align-middle mb-0">
                <thead>
                  <tr>
                    <th>{escape(enabled_label)}</th>
                    <th>{escape(task_name_label)}</th>
                    <th>{escape(task_category_label)}</th>
                    <th>{escape(task_action_label)}</th>
                    <th>{escape(task_next_run_label)}</th>
                    <th>{escape(task_owner_label)}</th>
                    <th>{escape(edit_label)}</th>
                  </tr>
                </thead>
                <tbody id="task-table-body"></tbody>
              </table>
            </div>
          </section>
          <details class="section-toggle">
            <summary>{escape(ui['import_config'])}</summary>
            <div class="toggle-body">
              <div class="import-box">
                <label for="import-options">{escape(ui['import_config'])}</label>
                <textarea id="import-options" rows="8" placeholder='{{"log_level":"debug"}}'></textarea>
                <button class="accent" onclick="importOptions()">{escape(ui['import_apply'])}</button>
              </div>
            </div>
          </details>
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
    <div class="modal fade" id="task-modal" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-lg modal-dialog-scrollable">
        <div class="modal-content bg-dark text-light border-secondary">
          <form id="task-form">
            <div class="modal-header border-secondary">
              <h5 id="task-modal-title" class="modal-title">{escape(modal_create_title)}</h5>
              <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <div id="task-form-alert" class="alert alert-danger d-none" role="alert"></div>
              <input id="task-id" type="hidden">
              <div class="row g-3">
                <div class="col-12">
                  <label class="form-label" for="task-type">{escape(task_type_label)}</label>
                  <select id="task-type" class="form-select" required>
                    {task_type_options_html}
                  </select>
                </div>
                <div class="col-12">
                  <label class="form-label d-block mb-2">{escape(task_days_label)}</label>
                  <div class="row g-2" id="weekday-group">
                    {weekday_checkboxes}
                  </div>
                </div>
                <div class="col-md-6">
                  <label class="form-label" for="task-hour">{escape(task_hour_label)}</label>
                  <select id="task-hour" class="form-select" required>
                    {hour_options}
                  </select>
                </div>
                <div class="col-md-6">
                  <label class="form-label" for="task-minute">{escape(task_minute_label)}</label>
                  <select id="task-minute" class="form-select">
                    {minute_options}
                  </select>
                </div>
                <div class="col-12">
                  <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" role="switch" id="task-enabled" checked>
                    <label class="form-check-label" for="task-enabled">{escape(enabled_label)}</label>
                  </div>
                </div>
              </div>
            </div>
            <div class="modal-footer border-secondary">
              <button type="button" class="btn btn-outline-light" data-bs-dismiss="modal">{escape(cancel_label)}</button>
              <button type="submit" class="btn btn-primary">{escape(save_label)}</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
      const weekdayOrder = {weekday_order_json};
      const weekdayLabels = {weekday_labels_json};
      const uiText = {task_ui_json};
      let taskList = {task_data_json};

      const taskModalElement = document.getElementById('task-modal');
      const taskModal = new bootstrap.Modal(taskModalElement);

      function pad(value) {{
        return String(value).padStart(2, '0');
      }}

      function escapeHtml(value) {{
        return String(value ?? '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#039;');
      }}

      function setFormAlert(message) {{
        const alert = document.getElementById('task-form-alert');
        if (!message) {{
          alert.classList.add('d-none');
          alert.textContent = '';
          return;
        }}
        alert.classList.remove('d-none');
        alert.textContent = message;
      }}

      function setActionResult(message, isError = false) {{
        const output = document.getElementById('action-result');
        output.textContent = message || '';
        output.classList.toggle('is-error', isError);
      }}

      function formatWeekdays(days) {{
        if (!Array.isArray(days) || !days.length) {{
          return '-';
        }}
        return days.map((day) => weekdayLabels[day] || day).join(', ');
      }}

      function formatNextRun(value) {{
        if (!value) {{
          return '-';
        }}
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {{
          return value;
        }}
        return parsed.toLocaleString();
      }}

      function formatTaskSchedule(task) {{
        const hour = pad(Number.parseInt(task.hour ?? 0, 10));
        const minute = pad(Number.parseInt(task.minute ?? 0, 10));
        return `${{formatWeekdays(task.weekdays)}} @ ${{hour}}:${{minute}}`;
      }}

      function sortedTasks(tasks) {{
        const order = {{ auto_check_update: 0, auto_update: 1 }};
        return [...tasks].sort((left, right) => {{
          const orderLeft = order[left.task_type] ?? 99;
          const orderRight = order[right.task_type] ?? 99;
          if (orderLeft !== orderRight) {{
            return orderLeft - orderRight;
          }}
          return String(left.id || '').localeCompare(String(right.id || ''));
        }});
      }}

      function renderTaskRows() {{
        const body = document.getElementById('task-table-body');
        const tasks = sortedTasks(Array.isArray(taskList) ? taskList : []);
        if (!tasks.length) {{
          body.innerHTML = `<tr><td colspan="7" class="text-center text-secondary py-3">${{escapeHtml(uiText.noTasks)}}</td></tr>`;
          return;
        }}
        body.innerHTML = tasks
          .map((task) => {{
            const schedule = formatTaskSchedule(task);
            return `
              <tr>
                <td>
                  <div class="form-check form-switch mb-0">
                    <input
                      class="form-check-input task-enabled-toggle"
                      type="checkbox"
                      data-task-id="${{escapeHtml(task.id)}}"
                      ${{task.enabled ? 'checked' : ''}}
                    >
                  </div>
                </td>
                <td>${{escapeHtml(task.name || task.task_type)}}</td>
                <td>${{escapeHtml(task.category || 'System')}}</td>
                <td>
                  <div>${{escapeHtml(task.action || '')}}</div>
                  <div class="text-secondary small">${{escapeHtml(schedule)}}</div>
                </td>
                <td>${{escapeHtml(formatNextRun(task.next_run))}}</td>
                <td>${{escapeHtml(task.owner || 'HA AutoUpgrade')}}</td>
                <td>
                  <button type="button" class="btn btn-sm btn-outline-light task-edit-btn" data-task-id="${{escapeHtml(task.id)}}">
                    ${{escapeHtml(uiText.edit)}}
                  </button>
                </td>
              </tr>
            `;
          }})
          .join('');
      }}

      const dashboardBaseUrl = (() => {{
        const current = new URL(window.location.href);
        if (!current.pathname.endsWith('/')) {{
          current.pathname = `${{current.pathname}}/`;
        }}
        current.search = '';
        current.hash = '';
        return current;
      }})();
      function resolveDashboardUrl(path) {{
        return new URL(path.replace(/^\\/+/, ''), dashboardBaseUrl).toString();
      }}

      async function apiJson(url, method = 'GET', body = null) {{
        const response = await fetch(resolveDashboardUrl(url), {{
          method,
          headers: {{ 'Content-Type': 'application/json' }},
          body: body ? JSON.stringify(body) : null
        }});
        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          throw new Error(payload.error || uiText.unknownError);
        }}
        return payload;
      }}

      async function postAction(url, body = null) {{
        const result = await apiJson(url, 'POST', body);
        setActionResult(JSON.stringify(result, null, 2));
        setTimeout(() => window.location.reload(), 1500);
      }}

      async function refreshTasks() {{
        const payload = await apiJson('/api/tasks');
        taskList = Array.isArray(payload.tasks) ? payload.tasks : [];
        renderTaskRows();
      }}

      function selectedWeekdays() {{
        return weekdayOrder.filter((day) => {{
          const checkbox = document.getElementById(`weekday-${{day}}`);
          return checkbox && checkbox.checked;
        }});
      }}

      function fillTaskForm(task = null) {{
        setFormAlert('');
        document.getElementById('task-id').value = task?.id || '';
        document.getElementById('task-type').value = task?.task_type || 'auto_check_update';
        document.getElementById('task-hour').value = pad(Number.parseInt(task?.hour ?? 0, 10));
        const minuteValue = Number.parseInt(task?.minute ?? 0, 10);
        document.getElementById('task-minute').value = task ? pad(minuteValue) : '';
        document.getElementById('task-enabled').checked = task ? Boolean(task.enabled) : true;

        weekdayOrder.forEach((day) => {{
          const checkbox = document.getElementById(`weekday-${{day}}`);
          if (!checkbox) {{
            return;
          }}
          checkbox.checked = task ? Array.isArray(task.weekdays) && task.weekdays.includes(day) : false;
        }});

        if (!task) {{
          const monday = document.getElementById('weekday-mon');
          if (monday) {{
            monday.checked = true;
          }}
        }}

        document.getElementById('task-modal-title').textContent = task ? uiText.editTitle : uiText.createTitle;
      }}

      function openTaskModal(task = null) {{
        fillTaskForm(task);
        taskModal.show();
      }}

      document.getElementById('create-task-btn').addEventListener('click', () => openTaskModal());

      document.getElementById('task-form').addEventListener('submit', async (event) => {{
        event.preventDefault();
        const taskId = document.getElementById('task-id').value;
        const weekdays = selectedWeekdays();
        if (!weekdays.length) {{
          setFormAlert(uiText.validationDays);
          return;
        }}
        const minuteRaw = document.getElementById('task-minute').value;
        const payload = {{
          task_type: document.getElementById('task-type').value,
          weekdays,
          hour: Number.parseInt(document.getElementById('task-hour').value, 10),
          minute: minuteRaw === '' ? 0 : Number.parseInt(minuteRaw, 10),
          enabled: document.getElementById('task-enabled').checked
        }};
        try {{
          const isEdit = Boolean(taskId);
          const endpoint = isEdit
            ? `/api/tasks/${{encodeURIComponent(taskId)}}`
            : '/api/tasks';
          const method = isEdit ? 'PUT' : 'POST';
          const result = await apiJson(endpoint, method, payload);
          taskList = Array.isArray(result.tasks) ? result.tasks : taskList;
          renderTaskRows();
          taskModal.hide();
          setActionResult(isEdit ? uiText.updated : uiText.created);
        }} catch (error) {{
          setFormAlert(error.message || uiText.unknownError);
        }}
      }});

      document.getElementById('task-table-body').addEventListener('click', (event) => {{
        const button = event.target.closest('.task-edit-btn');
        if (!button) {{
          return;
        }}
        const taskId = button.getAttribute('data-task-id') || '';
        const task = (Array.isArray(taskList) ? taskList : []).find((entry) => entry.id === taskId);
        if (task) {{
          openTaskModal(task);
        }}
      }});

      document.getElementById('task-table-body').addEventListener('change', async (event) => {{
        const toggle = event.target.closest('.task-enabled-toggle');
        if (!toggle) {{
          return;
        }}
        const taskId = toggle.getAttribute('data-task-id') || '';
        const desiredState = toggle.checked;
        try {{
          const result = await apiJson(
            `/api/tasks/${{encodeURIComponent(taskId)}}/enabled`,
            'POST',
            {{ enabled: desiredState }}
          );
          taskList = Array.isArray(result.tasks) ? result.tasks : taskList;
          renderTaskRows();
          setActionResult(uiText.enabledUpdated);
        }} catch (error) {{
          toggle.checked = !desiredState;
          setActionResult(error.message || uiText.unknownError, true);
        }}
      }});

      async function importOptions() {{
        const raw = document.getElementById('import-options').value.trim();
        if (!raw) {{
          setActionResult('No JSON provided.', true);
          return;
        }}
        let parsed;
        try {{
          parsed = JSON.parse(raw);
        }} catch (_error) {{
          setActionResult('Invalid JSON payload.', true);
          return;
        }}
        try {{
          const result = await apiJson('/api/actions/import', 'POST', {{ options: parsed }});
          setActionResult(JSON.stringify(result, null, 2));
          setTimeout(() => window.location.reload(), 1500);
        }} catch (error) {{
          setActionResult(error.message || uiText.unknownError, true);
        }}
      }}

      renderTaskRows();
      refreshTasks().catch((error) => setActionResult(error.message || uiText.unknownError, true));
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
        if method == "GET" and parsed.path == "/api/tasks":
          return self._json(200, {"tasks": self.service.list_schedule_tasks()})
        if method == "GET" and parsed.path == "/static/dashboard.css":
            return self._text(200, self._dashboard_css(), "text/css; charset=utf-8")

        task_path = [part for part in parsed.path.split("/") if part]
        if task_path[:2] == ["api", "tasks"]:
          try:
            if method == "POST" and parsed.path == "/api/tasks":
              payload = self._decode_json_body(body)
              created = self.service.create_schedule_task(payload)
              return self._json(
                201,
                {
                  "status": "created",
                  "task": created,
                  "tasks": self.service.list_schedule_tasks(),
                },
              )

            if len(task_path) == 3 and method == "PUT":
              task_id = unquote(task_path[2])
              payload = self._decode_json_body(body)
              updated = self.service.update_schedule_task(task_id, payload)
              return self._json(
                200,
                {
                  "status": "updated",
                  "task": updated,
                  "tasks": self.service.list_schedule_tasks(),
                },
              )

            if len(task_path) == 4 and task_path[3] == "enabled" and method == "POST":
              task_id = unquote(task_path[2])
              payload = self._decode_json_body(body)
              if "enabled" not in payload:
                raise ValueError("Missing enabled value")
              updated = self.service.set_schedule_task_enabled(task_id, payload["enabled"])
              return self._json(
                200,
                {
                  "status": "updated",
                  "task": updated,
                  "tasks": self.service.list_schedule_tasks(),
                },
              )
          except ValueError as err:
            return self._json(400, {"status": "error", "error": str(err)})

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
            try:
                payload = self._decode_json_body(body)
                return self._json(200, self.service.import_configuration(payload))
            except ValueError as err:
                return self._json(400, {"status": "error", "error": str(err)})
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

            def do_PUT(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                status, content_type, payload = server.handle_request(
                    method="PUT",
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
