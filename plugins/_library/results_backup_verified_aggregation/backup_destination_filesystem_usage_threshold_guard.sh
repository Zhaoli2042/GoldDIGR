# ── SNIPPET: results_backup_verified_aggregation/backup_destination_filesystem_usage_threshold_guard ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From backup_results.sh check_disk_usage().
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

DEST_BASE="{{DEST_BASE}}"
DISK_ALERT_THRESHOLD={{DISK_ALERT_THRESHOLD:-90}}

if [ ! -d "$DEST_BASE" ]; then
  echo "Warning: Destination base $DEST_BASE does not exist yet"
  exit 0
fi

usage=$(df "$DEST_BASE" 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')
if [ -n "$usage" ] && [ "$usage" -ge "$DISK_ALERT_THRESHOLD" ]; then
  echo "ALERT: Destination storage is ${usage}% full! (threshold: ${DISK_ALERT_THRESHOLD}%)"
  exit 1
fi

echo "Destination disk usage: ${usage}%"
