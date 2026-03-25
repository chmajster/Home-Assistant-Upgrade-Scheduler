"""Application entry point."""

from __future__ import annotations

import logging
import signal
import threading

from ha_autoupgrade.config import load_config
from ha_autoupgrade.service import AutoUpgradeService
from ha_autoupgrade.utils.logging_utils import setup_logging
from ha_autoupgrade.web.server import DashboardServer


def main() -> None:
    config = load_config()
    log_handler = setup_logging(config.log_level, config.json_logs)
    logger = logging.getLogger("ha_autoupgrade.main")
    service = AutoUpgradeService(config, log_handler)
    web_server = DashboardServer(service)

    stop_event = threading.Event()

    def _stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    web_thread = threading.Thread(target=web_server.run, name="dashboard-server", daemon=True)
    web_thread.start()
    logger.info("HA AutoUpgrade started")

    while not stop_event.is_set():
        try:
            service.tick()
        except Exception:
            logger.exception("Unhandled error in service loop")
        stop_event.wait(5)

    logger.info("HA AutoUpgrade stopped")


if __name__ == "__main__":
    main()
