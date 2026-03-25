# HA AutoUpgrade

HA AutoUpgrade is a Supervisor-based Home Assistant add-on that automates update checks and, when allowed by policy, executes controlled update runs for:

- Home Assistant Core
- Home Assistant Supervisor
- Home Assistant OS
- installed add-ons

It is intended for Home Assistant OS and Supervised installations where Supervisor API endpoints are available.

The runtime is intentionally implemented with the Python standard library only. That keeps image builds independent from external Python package indexes, which is useful on installations with restricted outbound DNS or package access during Supervisor builds.

## What It Does

- discovers available updates from Supervisor
- evaluates safety and policy gates before execution
- optionally creates a Home Assistant backup before updating
- executes serial updates with configurable ordering
- keeps audit history and state in `/data`
- sends notifications through persistent notifications, notify services, webhook, and optional SMTP
- exposes a lightweight ingress dashboard and machine-readable status/health API

## Repository Layout

```text
ha_auto_upgrade/
├── apparmor.txt
├── build.yaml
├── CHANGELOG.md
├── config.yaml
├── DOCS.md
├── Dockerfile
├── examples/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── run.sh
├── src/ha_autoupgrade/
├── tests/
└── translations/
```

## Installation

1. Publish this repository to a Git service reachable by Home Assistant.
2. Open `Settings -> Add-ons -> Add-on Store`.
3. Use `Repositories` from the store menu.
4. Add the repository URL.
5. Install `HA AutoUpgrade`.
6. Review the add-on options before starting it.
7. Open the ingress panel to review status and test the policy gates.

## Runtime Architecture

The add-on is a Python service with these major modules:

- `api/`
  - Supervisor and Home Assistant API client.
- `scheduler/`
  - interval, cron, and weekday/time scheduling.
- `policies/`
  - execution rules and candidate filtering.
- `backups/`
  - backup creation, retention, and guarded rollback request flow.
- `updates/`
  - update discovery, planning, ordering, and execution.
- `notifications/`
  - persistent notifications, notify service calls, webhook, and SMTP.
- `storage/`
  - state file, retry queue, safe mode state, and append-only audit history.
- `web/`
  - ingress dashboard and local API.
- `utils/`
  - logging, locks, time parsing, version helpers, and system inspection.

## Update Flow

1. The scheduler or dashboard triggers a `check`, `install`, `backup`, `retry`, or `self-test` action.
2. For install runs, the add-on evaluates:
   - safe mode / cooldown state
   - disk, memory, CPU load, API availability, local Supervisor reachability
   - maintenance window and blackout dates
   - approval and entity-state rules
3. The planner reloads update metadata and builds a filtered update plan.
4. If enabled, the add-on creates a Home Assistant backup using Supervisor backup APIs.
5. Pre-update actions run:
   - optional maintenance service
   - helper entities on/off
   - configured Home Assistant services
6. Updates are executed serially according to `update_strategy`.
7. After each step, the add-on performs a basic post-update health check.
8. Results are written to state and audit history and notifications are dispatched.
9. Post-update actions run, including selected add-on restarts and Home Assistant services.

## Safety Model

Safe-by-default behaviors include:

- no automatic update outside the configured maintenance window
- no update if configured thresholds fail
- no secret values in exported diagnostics
- no host network access requirement
- ingress-first UI access
- process lock to prevent overlapping runs
- cooldown and safe mode after repeated failures

## Configuration Notes

The add-on configuration exposed in Home Assistant is intentionally minimal:

- `check_interval_minutes`
  - how often the add-on checks for updates
- `auto_install`
  - if enabled, scheduled checks can also trigger scheduled installs
- `create_backup`
  - whether a Home Assistant backup is created before an install run

Advanced safety and policy controls still exist in the code with safe defaults, but they are no longer exposed in the normal add-on options UI.

## Scheduling

The visible configuration uses one interval:

- `check_interval_minutes`

That interval controls scheduled update checks.

If `auto_install` is enabled, the same interval is also used for scheduled install attempts.

Manual actions from the dashboard remain available regardless of the scheduler settings.

## Web UI and API

The ingress dashboard shows:

- health state
- pending updates
- last check and last run
- next scheduled install
- last backup
- audit trail
- recent logs buffer

Manual actions:

- check now
- check and install now
- update now
- install only Core
- install only Supervisor
- install only OS
- install only add-ons
- backup now
- retry failed items
- clear stuck state
- export diagnostics
- run self-test
- import configuration

Key endpoints:

- `GET /api/status`
- `GET /api/health`
- `GET /api/history`
- `POST /api/actions/check`
- `POST /api/actions/check-install`
- `POST /api/actions/update`
- `POST /api/actions/update/core`
- `POST /api/actions/update/supervisor`
- `POST /api/actions/update/os`
- `POST /api/actions/update/addons`
- `POST /api/actions/backup`
- `POST /api/actions/retry`
- `POST /api/actions/clear`
- `POST /api/actions/export`
- `POST /api/actions/self-test`
- `POST /api/actions/import`
- `POST /api/webhook/trigger`

## Rollback Limits

Automatic rollback is intentionally conservative.

- If `rollback_on_failure` is disabled, the add-on records the failure and keeps the backup ID for manual recovery.
- If rollback is enabled and the backup mode is `full`, the add-on can request a full backup restore through Supervisor.
- Partial-backup rollback is not automated.
- Some update types, especially Supervisor or OS updates, can restart the environment mid-run. In those cases the add-on marks the run as interrupted on next start and keeps a retry queue where appropriate.

## Security-Only Mode

Supervisor does not universally expose a reliable security-classification field for every update target.

- If a component exposes a security flag, that is used.
- Otherwise the add-on falls back to a patch-level version policy.
- This means `security_only_mode` should be treated as a guarded best-effort mode, not a formal CVE-only guarantee.

## Diagnostics and Observability

State is stored in `/data/state.json`.  
Audit history is stored in `/data/history.jsonl`.  
Exported diagnostic bundles are written to `/data/exports/`.

The diagnostic archive contains:

- redacted configuration
- current state
- recent audit events
- recent in-memory logs

## Development

Local development files:

- [pyproject.toml](/c:/Users/Chris/Documents/GitHub/Home-Assistant-Upgrade-Scheduler/ha_auto_upgrade/pyproject.toml)
- [requirements-dev.txt](/c:/Users/Chris/Documents/GitHub/Home-Assistant-Upgrade-Scheduler/ha_auto_upgrade/requirements-dev.txt)
- [.devcontainer/devcontainer.json](/c:/Users/Chris/Documents/GitHub/Home-Assistant-Upgrade-Scheduler/.devcontainer/devcontainer.json)

Run tests locally in a Python 3.12 environment:

```powershell
cd ha_auto_upgrade
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -q
```

## Limitations

- This add-on depends on Supervisor endpoints and is not intended for unsupported installation types without Supervisor.
- Full unattended rollback is intentionally limited because restore operations can restart or destabilize the system.
- Health verification after an update is intentionally lightweight and focuses on Supervisor/API reachability and Home Assistant state.
- The dashboard is ingress-first and restricts direct access unless requests originate from local or Supervisor network ranges.
