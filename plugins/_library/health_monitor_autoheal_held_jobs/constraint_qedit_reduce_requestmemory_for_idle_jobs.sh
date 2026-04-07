# ── SNIPPET: health_monitor_autoheal_held_jobs/constraint_qedit_reduce_requestmemory_for_idle_jobs ─
# Scheduler:   htcondor
# Tool:        any
# Tested:      golddigr
# Notes: From apply_memory_fix.sh step 4.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

USER_ID="{{USER_ID:-$USER}}"
NEW_MEMORY_MB="{{NEW_MEMORY_MB:-6144}}"

command -v condor_q >/dev/null 2>&1 || { echo "condor_q not available"; exit 0; }

IDLE_COUNT=$(condor_q "$USER_ID" -constraint 'JobStatus == 1' -af ClusterId 2>/dev/null | wc -l)
RUNNING_COUNT=$(condor_q "$USER_ID" -constraint 'JobStatus == 2' -af ClusterId 2>/dev/null | wc -l)

echo "Idle jobs:    $IDLE_COUNT"
echo "Running jobs: $RUNNING_COUNT"

if [ "$IDLE_COUNT" -gt 0 ]; then
  condor_qedit -constraint "Owner == \"$USER_ID\" && JobStatus == 1" RequestMemory "$NEW_MEMORY_MB" 2>/dev/null
  echo "Updated $IDLE_COUNT idle jobs to ${NEW_MEMORY_MB} MB"
fi
