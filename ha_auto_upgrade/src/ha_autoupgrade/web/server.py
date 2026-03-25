"""Ingress dashboard and local API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request
import yaml

from ha_autoupgrade.constants import (
    ALLOWED_DASHBOARD_IPS,
    ALLOWED_DASHBOARD_PREFIXES,
    TRANSLATIONS_DIR,
    WEB_PORT,
)


class DashboardServer:
    def __init__(self, service) -> None:
        self.service = service
        self.logger = logging.getLogger("ha_autoupgrade.web")
        self.app = Flask(
            __name__,
            template_folder="templates",
            static_folder="static",
        )
        self.translations = self._load_translations()
        self._register_routes()

    def _load_translations(self) -> dict[str, dict[str, Any]]:
        payload: dict[str, dict[str, Any]] = {}
        for language in ("en", "pl"):
            path = TRANSLATIONS_DIR / f"{language}.yaml"
            if path.exists():
                payload[language] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            else:
                payload[language] = {}
        return payload

    def _register_routes(self) -> None:
        @self.app.before_request
        def _protect_dashboard() -> None:
            if request.path.startswith("/api/webhook/trigger"):
                return
            if request.path.startswith("/static/"):
                return
            remote_addr = request.remote_addr or ""
            if remote_addr in ALLOWED_DASHBOARD_IPS:
                return
            if any(remote_addr.startswith(prefix) for prefix in ALLOWED_DASHBOARD_PREFIXES):
                return
            abort(403)

        @self.app.get("/")
        def index():
            language = self._language()
            return render_template(
                "dashboard.html",
                ui=self.translations.get(language, self.translations["en"]).get("ui", {}),
                lang=language,
                status=self.service.status(),
                health=self.service.health(),
            )

        @self.app.get("/api/status")
        def api_status():
            return jsonify(self.service.status())

        @self.app.get("/api/health")
        def api_health():
            return jsonify(self.service.health())

        @self.app.get("/api/history")
        def api_history():
            return jsonify(self.service.status()["recent_history"])

        @self.app.post("/api/actions/check")
        def action_check():
            self.service.enqueue_action("check", "dashboard")
            return jsonify({"status": "queued", "action": "check"})

        @self.app.post("/api/actions/update")
        def action_update():
            self.service.enqueue_action("install", "dashboard")
            return jsonify({"status": "queued", "action": "install"})

        @self.app.post("/api/actions/backup")
        def action_backup():
            self.service.enqueue_action("backup", "dashboard")
            return jsonify({"status": "queued", "action": "backup"})

        @self.app.post("/api/actions/retry")
        def action_retry():
            self.service.enqueue_action("retry", "dashboard")
            return jsonify({"status": "queued", "action": "retry"})

        @self.app.post("/api/actions/clear")
        def action_clear():
            self.service.enqueue_action("clear", "dashboard")
            return jsonify({"status": "queued", "action": "clear"})

        @self.app.post("/api/actions/export")
        def action_export():
            return jsonify(self.service.export_diagnostics())

        @self.app.post("/api/actions/self-test")
        def action_self_test():
            return jsonify(self.service.self_test())

        @self.app.post("/api/actions/import")
        def action_import():
            payload = request.get_json(silent=True) or {}
            return jsonify(self.service.import_configuration(payload))

        @self.app.post("/api/webhook/trigger")
        def webhook_trigger():
            configured = self.service.config.webhook_trigger_token
            provided = request.args.get("token", "")
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                provided = auth_header[7:]
            if configured and provided != configured:
                abort(401)
            self.service.enqueue_action("install", "webhook")
            return jsonify({"status": "queued", "action": "install"})

    def _language(self) -> str:
        requested = request.args.get("lang", "")
        if requested in self.translations:
            return requested
        accept = request.headers.get("Accept-Language", "").lower()
        if accept.startswith("pl"):
            return "pl"
        return "en"

    def run(self) -> None:
        self.app.run(host="0.0.0.0", port=WEB_PORT, debug=False, threaded=True, use_reloader=False)
