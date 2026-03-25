# Changelog

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
