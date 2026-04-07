# ── SNIPPET: workflow_bootstrap_start/restart_only_submit_tmux_session_to_pick_up_new_chunks ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From add_data.sh step 5.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

SCRIPT_DIR="{{SCRIPT_DIR:-$(cd "$(dirname "$0")" && pwd)}}"
SUBMIT_CMD="{{SUBMIT_CMD:-./monitor_submit.sh}}"

command -v tmux >/dev/null 2>&1 || { echo "tmux not available"; exit 1; }

if tmux has-session -t submit 2>/dev/null; then
  tmux kill-session -t submit 2>/dev/null || true
  sleep 2
fi

tmux new-session -d -s submit "cd $SCRIPT_DIR && $SUBMIT_CMD"
echo "Started tmux session: submit"
