# Changelog

## 1.0.8

- fixed startup crash when legacy saved options contain wildcard values such as `install_hour: "*"`
- added safe fallback handling for wildcard/default values in the simplified install schedule settings

## 1.0.7

- version bump from 1.0.6 to 1.0.7

## 1.0.6

- fixed add-on startup permissions by allowing `/init`, S6, Bashio, and Python runtime paths in the custom AppArmor profile
- kept the add-on in the official Supervisor container model instead of disabling the add-on runtime structure

## 1.0.5

- added visible add-on options for automatic install weekdays and install hour
- scheduled install runs now use the selected weekday set and time instead of only the generic interval
- manual `check updates and install` runs bypass automatic maintenance-window/day gating
- added dashboard schedule summary and kept the combined check-and-install button visible

## 1.0.4

- added richer operational logging for checks, plans, backups, installs, and summaries
- added a manual `check and install now` action
- added manual scoped install actions for Core, Supervisor, OS, and add-ons

## 1.0.3

- version bump from 1.0.2 to 1.0.3

## 1.0.2

- simplified add-on configuration to three options only:
- `check_interval_minutes`
- `auto_install`
- `create_backup`
- removed complex Home Assistant add-on schema entries from the visible configuration

## 1.0.1

- maintenance release
- bumped add-on version from 1.0.0 to 1.0.1

## 1.0.0

- initial production-oriented release of HA AutoUpgrade
- Supervisor-backed update discovery for Core, Supervisor, OS, and add-ons
- policy engine with maintenance windows, blackout dates, exclusions, approval entity, and staged rollout
- backup workflow with retention and guarded rollback request path
- scheduler with interval, cron, and fixed weekday/time modes
- ingress dashboard and local status API
- JSON or human-readable logging
- persistent state, retry queue, self-test, and diagnostic bundle export
- English and Polish translation files
- unit and integration-test scaffolding
