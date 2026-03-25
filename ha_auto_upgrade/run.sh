#!/usr/bin/with-contenv bashio
set -euo pipefail

export PYTHONUNBUFFERED=1
export PYTHONPATH=/app/src

exec python -m ha_autoupgrade.main
