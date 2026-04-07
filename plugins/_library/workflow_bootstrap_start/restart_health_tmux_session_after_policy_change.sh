# ── SNIPPET: workflow_bootstrap_start/restart_health_tmux_session_after_policy_change ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From apply_memory_fix.sh step 5.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

SCRIPT_DIR="{{SCRIPT_DIR:-$(cd "$(dirname "$0")" && pwd)}}"
HEALTH_CMD="{{HEALTH_CMD:-./monitor_health.sh}}"

command -v tmux >/dev/null 2>&1 || { echo "tmux not available"; exit 1; }

if tmux has-session -t health 2>/dev/null; then
  tmux kill-session -t health 2>/dev/null || true
  sleep 1
fi

tmux new-session -d -s health "cd $SCRIPT_DIR && $HEALTH_CMD"
echo "Health monitor restarted"
