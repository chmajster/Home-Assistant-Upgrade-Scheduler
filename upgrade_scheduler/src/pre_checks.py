"""Pre-update health checks for Home Assistant Upgrade Scheduler.

Verifies that the system is in a suitable state before any updates are applied.
All checks are non-destructive and read-only.
"""

import logging
from dataclasses import dataclass, field
from typing import List

from supervisor_api import SupervisorClient, SupervisorAPIError

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    passed: bool
    failures: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.passed:
            return "All pre-checks passed."
        return "Pre-check failures: " + "; ".join(self.failures)


class PreCheckRunner:
    """Runs a series of pre-update checks against the Supervisor API."""

    def __init__(
        self,
        client: SupervisorClient,
        cpu_threshold: int = 80,
        memory_threshold: int = 80,
    ) -> None:
        self._client = client
        self._cpu_threshold = cpu_threshold
        self._memory_threshold = memory_threshold

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run_all(self) -> CheckResult:
        failures: List[str] = []

        checks = [
            self._check_supervisor_healthy,
            self._check_core_healthy,
            self._check_host_resources,
        ]

        for check in checks:
            try:
                failure = check()
                if failure:
                    failures.append(failure)
            except SupervisorAPIError as exc:
                failures.append(f"API error during {check.__name__}: {exc}")
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(f"Unexpected error during {check.__name__}: {exc}")

        passed = len(failures) == 0
        result = CheckResult(passed=passed, failures=failures)
        if passed:
            logger.info("Pre-checks: all passed.")
        else:
            logger.warning("Pre-checks: %d failure(s): %s", len(failures), failures)
        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_supervisor_healthy(self) -> str:
        """Return an error string if Supervisor is not in a healthy state."""
        info = self._client.get_supervisor_info()
        healthy = info.get("healthy", True)
        if not healthy:
            return "Supervisor reports unhealthy state"
        return ""

    def _check_core_healthy(self) -> str:
        """Return an error string if Core is not running/healthy."""
        info = self._client.get_core_info()
        state = info.get("state", "running")
        if state not in ("running", "started"):
            return f"Core is not running (state={state})"
        return ""

    def _check_host_resources(self) -> str:
        """Return an error string if CPU or memory usage exceeds thresholds."""
        info = self._client.get_host_info()

        cpu_percent = info.get("cpu_percent")
        if cpu_percent is not None and cpu_percent > self._cpu_threshold:
            return (
                f"CPU usage {cpu_percent:.1f}% exceeds threshold "
                f"{self._cpu_threshold}%"
            )

        mem_data = info.get("memory", {})
        if isinstance(mem_data, dict):
            total = mem_data.get("total", 0)
            used = mem_data.get("used", 0)
            if total > 0:
                mem_percent = (used / total) * 100
                if mem_percent > self._memory_threshold:
                    return (
                        f"Memory usage {mem_percent:.1f}% exceeds threshold "
                        f"{self._memory_threshold}%"
                    )

        return ""
