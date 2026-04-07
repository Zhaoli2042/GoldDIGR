# ── SNIPPET: results_backup_verified_aggregation/eligible_tarball_selection_by_min_age_and_quiet_time ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From backup_results.sh find_eligible_files().
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

RESULTS_DIR="{{RESULTS_DIR:-results}}"
MIN_FILE_AGE={{MIN_FILE_AGE:-14400}}
MIN_QUIET_TIME={{MIN_QUIET_TIME:-600}}

now=$(date +%s)
min_age_cutoff=$((now - MIN_FILE_AGE))
quiet_cutoff=$((now - MIN_QUIET_TIME))

find "$RESULTS_DIR" -name "*_results.tar.gz" -type f 2>/dev/null | while read -r file; do
  mtime=$(stat -c %Y "$file" 2>/dev/null || true)
  [ -z "$mtime" ] && continue
  if [ "$mtime" -lt "$min_age_cutoff" ] && [ "$mtime" -lt "$quiet_cutoff" ]; then
    echo "$file"
  fi
done
