# Home Assistant Upgrade Scheduler

A Home Assistant add-on that automates the update process for Home Assistant Core, Supervisor, and installed add-ons in a controlled, unattended manner.

---

## Features

| Feature | Description |
|---|---|
| **Cron scheduling** | Define a standard 5-field cron expression to control exactly when updates run (e.g. every Sunday at 03:00). |
| **Selective updates** | Choose to update Core, Supervisor, and/or add-ons independently. Exclude specific add-ons by slug. |
| **Pre-update health checks** | Verify CPU & memory usage and service state before applying any changes. Abort automatically if thresholds are exceeded. |
| **Automatic backup** | Create a full system backup before every update run. Configurable name prefix and retention count. |
| **Rollback on failure** | Optionally restore the pre-update backup when any update fails. |
| **Persistent notifications** | Send success/failure notifications directly to the Home Assistant UI. |
| **Silent mode** | Suppress all UI notifications and rely solely on the add-on log. |
| **Force update** | Apply updates even when Supervisor reports none are available. |
| **Offline operation** | No external services required. All communication is via the local Supervisor API. |
| **YAML & UI config** | All options are editable from the Home Assistant add-on UI or the `config.yaml` file. |

---

## Installation

1. In Home Assistant, navigate to **Settings → Add-ons → Add-on Store**.
2. Click the overflow menu (⋮) and select **Repositories**.
3. Add the URL of this repository.
4. Find **Upgrade Scheduler** in the list and click **Install**.

---

## Configuration

All options can be set from the add-on **Configuration** tab in the UI.

| Option | Type | Default | Description |
|---|---|---|---|
| `schedule_cron` | string | `0 3 * * 0` | Cron expression for when to run updates (UTC). |
| `update_core` | bool | `true` | Update Home Assistant Core. |
| `update_supervisor` | bool | `true` | Update the Supervisor. |
| `update_addons` | bool | `true` | Update all installed add-ons. |
| `addon_exclude` | list | `[]` | Add-on slugs to skip during updates. |
| `backup_before_update` | bool | `true` | Create a full backup before updating. |
| `backup_name_prefix` | string | `upgrade-scheduler` | Prefix for backup names. |
| `backup_keep_last` | int | `5` | Number of add-on-managed backups to retain (1–20). |
| `pre_check_enabled` | bool | `true` | Run health checks before updating. |
| `pre_check_cpu_threshold` | int | `80` | CPU usage % above which the update is aborted. |
| `pre_check_memory_threshold` | int | `80` | Memory usage % above which the update is aborted. |
| `force_update` | bool | `false` | Apply updates even when none are reported available. |
| `silent_mode` | bool | `false` | Suppress all UI notifications. |
| `notify_on_success` | bool | `true` | Send a UI notification on success. |
| `notify_on_failure` | bool | `true` | Send a UI notification on failure. |
| `rollback_on_failure` | bool | `false` | Restore the pre-update backup when an update fails. |
| `log_level` | string | `info` | Log verbosity: `debug`, `info`, `warning`, `error`. |

### Example configuration (YAML)

```yaml
schedule_cron: "0 3 * * 0"   # Every Sunday at 03:00 UTC
update_core: true
update_supervisor: true
update_addons: true
addon_exclude:
  - my_critical_addon
backup_before_update: true
backup_name_prefix: "auto-update"
backup_keep_last: 3
pre_check_enabled: true
pre_check_cpu_threshold: 70
pre_check_memory_threshold: 75
force_update: false
silent_mode: false
notify_on_success: true
notify_on_failure: true
rollback_on_failure: true
log_level: info
```

---

## How It Works

```
┌─────────────────────────────────────────────────────┐
│               Scheduler (cron loop)                  │
│  Fires when datetime.now(UTC) >= next_cron_trigger  │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│              Pre-Update Health Checks                │
│  • Supervisor healthy?                               │
│  • Core running?                                     │
│  • CPU & memory within thresholds?                   │
└────────────────────┬────────────────────────────────┘
                     │ pass
                     ▼
┌─────────────────────────────────────────────────────┐
│           Create Full Backup (optional)              │
│  • Timestamped name: <prefix>-YYYYMMDD-HHMMSS        │
│  • Enforces retention (keep_last oldest removed)     │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│                 Apply Updates                        │
│  1. Supervisor update (if enabled & available)       │
│  2. Core update      (if enabled & available)        │
│  3. Add-on updates   (if enabled, excluding listed)  │
└────────────────────┬────────────────────────────────┘
                     │
           ┌─────────┴──────────┐
       success                failure
           │                    │
           ▼                    ▼
     ✅ Notify            ┌──────────────┐
     success              │ Rollback?    │
                          │ (optional)   │
                          └──────┬───────┘
                                 │
                          ❌ Notify failure
```

---

## Architecture

```
upgrade_scheduler/
├── config.yaml           # Add-on manifest (options schema, permissions)
├── Dockerfile            # Container build instructions
├── run.sh                # Entry-point script
├── requirements.txt      # Python dependencies
├── translations/
│   └── en.yaml           # UI label translations
└── src/
    ├── main.py           # Bootstrap & orchestration
    ├── scheduler.py      # Cron-based event loop
    ├── supervisor_api.py # Home Assistant Supervisor REST client
    ├── pre_checks.py     # Pre-update health checks
    ├── backup_manager.py # Backup creation & retention
    ├── updater.py        # Update execution & rollback
    ├── notifier.py       # HA persistent notifications
    └── config_manager.py # Options loading & validation
```

---

## Development & Testing

```bash
# Install dependencies
pip install -r upgrade_scheduler/requirements.txt pytest

# Run tests
python -m pytest tests/ -v
```

---

## Security & Privacy

- All API communication is local (http://supervisor) — no data leaves the machine.
- The Supervisor token (`SUPERVISOR_TOKEN`) is injected by the HA framework and never stored.
- No external dependencies beyond the Python standard library, `requests`, and `croniter`.
