#!/usr/bin/with-contenv bashio
set -euo pipefail

LOG_LEVEL="$(bashio::config 'log_level')"
export EV_ORCH_LOG_LEVEL="$LOG_LEVEL"

bashio::log.info "Starting EV Orchestrator 0.3.1 in monitor/audit mode"
exec python3 -u /app/main.py
