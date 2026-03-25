"""Cron-based scheduler for Home Assistant Upgrade Scheduler.

Uses *croniter* to parse cron expressions and determine when the next update
run should be triggered.  The scheduler runs in a tight loop, sleeping in
short intervals so it can react quickly once the scheduled time arrives.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Callable

from croniter import croniter, CroniterBadCronError

logger = logging.getLogger(__name__)

TICK_SECONDS = 30  # How often the loop checks if a run is due


class Scheduler:
    """Runs a callable on the schedule defined by a cron expression."""

    def __init__(self, cron_expr: str, job: Callable[[], None]) -> None:
        self._cron_expr = cron_expr
        self._job = job
        self._validate_cron(cron_expr)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """Block forever, executing *job* whenever the cron schedule fires."""
        logger.info(
            "Scheduler started.  Cron expression: '%s'", self._cron_expr
        )
        next_run = self._next_run_time()
        logger.info("Next scheduled run: %s", next_run.isoformat())

        while True:
            now = datetime.now(timezone.utc)
            if now >= next_run:
                logger.info("Cron trigger at %s – starting update run.", now.isoformat())
                self._safe_execute()
                next_run = self._next_run_time()
                logger.info("Next scheduled run: %s", next_run.isoformat())
            time.sleep(TICK_SECONDS)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _next_run_time(self) -> datetime:
        """Calculate the next UTC datetime at which the cron fires."""
        return croniter(self._cron_expr, datetime.now(timezone.utc)).get_next(datetime)

    def _safe_execute(self) -> None:
        """Execute the job and swallow any unhandled exceptions."""
        try:
            self._job()
        except Exception as exc:  # pylint: disable=broad-except
            logger.critical("Unhandled exception in update job: %s", exc, exc_info=True)

    @staticmethod
    def _validate_cron(expr: str) -> None:
        try:
            croniter(expr)
        except (CroniterBadCronError, ValueError) as exc:
            raise ValueError(f"Invalid cron expression '{expr}': {exc}") from exc
