"""Notification dispatchers."""

from __future__ import annotations

from email.message import EmailMessage
import json
import logging
import smtplib
from typing import Any
from urllib import error, request

from ha_autoupgrade.api.supervisor import SupervisorClient
from ha_autoupgrade.config import AppConfig


class NotificationManager:
    def __init__(self, config: AppConfig, client: SupervisorClient, logger: logging.Logger) -> None:
        self.config = config
        self.client = client
        self.logger = logger

    def send(self, event_name: str, title: str, payload: dict[str, Any]) -> None:
        if not self.config.notification_enabled(event_name):
            return

        body = json.dumps(payload, indent=2, sort_keys=True)
        if self.config.notify_persistent:
            try:
                self.client.create_persistent_notification(
                    title,
                    f"```json\n{body}\n```",
                    f"ha_autoupgrade_{event_name}",
                )
            except Exception:
                self.logger.exception("Failed to create persistent notification")

        for service in self.config.notify_services:
            try:
                self.client.call_service(service, {"title": title, "message": body})
            except Exception:
                self.logger.exception("Failed to call notify service %s", service)

        if self.config.notify_webhook_url:
            headers = {"Content-Type": "application/json"}
            if self.config.notify_webhook_token:
                headers["Authorization"] = f"Bearer {self.config.notify_webhook_token}"
            try:
                req = request.Request(
                    url=self.config.notify_webhook_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with request.urlopen(req, timeout=15):
                    pass
            except (error.URLError, TimeoutError, OSError):
                self.logger.exception("Failed to deliver webhook notification")

        if self.config.smtp_enabled:
            try:
                message = EmailMessage()
                message["Subject"] = title
                message["From"] = self.config.smtp_from
                message["To"] = self.config.smtp_to
                message.set_content(body)
                with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=15) as smtp:
                    smtp.starttls()
                    if self.config.smtp_username:
                        smtp.login(self.config.smtp_username, self.config.smtp_password)
                    smtp.send_message(message)
            except Exception:
                self.logger.exception("Failed to deliver SMTP notification")
