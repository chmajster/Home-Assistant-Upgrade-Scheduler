#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Home Assistant Upgrade Scheduler..."

exec python3 /app/src/main.py
