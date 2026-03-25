# Home Assistant Add-on Repository: HA AutoUpgrade

This repository contains a production-focused Home Assistant add-on named **HA AutoUpgrade**.

The add-on automates update checks and controlled update execution for:

- Home Assistant Core
- Home Assistant Supervisor
- Home Assistant OS
- Installed add-ons

It is designed for Home Assistant installations where the Supervisor API is available (Home Assistant OS and Supervised deployments).

## Repository Structure

```text
.
├── repository.yaml
├── .devcontainer/
└── ha_auto_upgrade/
    ├── config.yaml
    ├── build.yaml
    ├── Dockerfile
    ├── run.sh
    ├── DOCS.md
    ├── CHANGELOG.md
    ├── translations/
    ├── src/
    ├── tests/
    └── examples/
```

## Install as a Custom Add-on Repository

1. Open Home Assistant.
2. Go to `Settings -> Add-ons -> Add-on Store`.
3. Click the menu (`⋮`) in the top-right corner.
4. Choose `Repositories`.
5. Add this repository URL.
6. Find **HA AutoUpgrade** in the store and install it.

## Core Capabilities

- Configurable update policy by component type and add-on exclusions.
- Pre-flight safety checks (disk, load, memory, network, API availability, Home Assistant state, optional entity-based checks).
- Optional pre-update backups with retention.
- Dry-run and notify-only modes.
- Scheduling modes: interval, cron, and weekday/time.
- Cooldown, rate limiting, safe mode, and watchdog protection.
- Event firing and multiple notification channels.
- Local ingress dashboard and health/status endpoints.

## Security Model

- Uses Supervisor token from environment (`SUPERVISOR_TOKEN`); token is never logged.
- Input validation for user options.
- Least-privilege runtime defaults in add-on configuration.
- Explicitly redacts secret fields from exported diagnostics.

## Documentation

- Add-on user and operator documentation: [ha_auto_upgrade/DOCS.md](/c:/Users/Chris/Documents/GitHub/Home-Assistant-Upgrade-Scheduler/ha_auto_upgrade/DOCS.md)
- Changelog: [ha_auto_upgrade/CHANGELOG.md](/c:/Users/Chris/Documents/GitHub/Home-Assistant-Upgrade-Scheduler/ha_auto_upgrade/CHANGELOG.md)

## Development

- Add-on source package: `ha_auto_upgrade/src/ha_autoupgrade`
- Unit tests: `ha_auto_upgrade/tests`
- Dev container config: [/.devcontainer/devcontainer.json](/c:/Users/Chris/Documents/GitHub/Home-Assistant-Upgrade-Scheduler/.devcontainer/devcontainer.json)

Run tests locally:

```powershell
cd ha_auto_upgrade
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest -q
```
