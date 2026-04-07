# ── SNIPPET: results_backup_verified_aggregation/resume_retry_backups_using_in_progress_manifests_and_tmp_validation ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From backup_results.sh resume_incomplete().
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

MANIFEST_DIR="{{MANIFEST_DIR:-.backup_manifests}}"

incomplete=$(grep -l "IN_PROGRESS\|FAILED" "$MANIFEST_DIR"/manifest_*.txt 2>/dev/null || true)
[ -z "$incomplete" ] && exit 0

for manifest in $incomplete; do
  dest=$(grep "^# Destination:" "$manifest" | cut -d' ' -f3)
  tmp_file="${dest}.tmp"
  status=$(grep "^# Status:" "$manifest" | tail -1 | cut -d' ' -f3)

  case "$status" in
    IN_PROGRESS)
      if [ -f "$tmp_file" ]; then
        if tar -tzf "$tmp_file" > /dev/null 2>&1; then
          if mv "$tmp_file" "$dest"; then
            grep -v "^#" "$manifest" | while read -r file; do
              [ -f "$file" ] && rm -f "$file"
            done
            sed -i 's/IN_PROGRESS/COMPLETE/' "$manifest"
          fi
        else
          rm -f "$tmp_file"
        fi
      fi
      ;;
    FAILED_*)
      rm -f "$manifest"
      ;;
  esac
done
