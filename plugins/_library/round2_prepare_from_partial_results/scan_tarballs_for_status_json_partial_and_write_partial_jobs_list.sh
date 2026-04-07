# ── SNIPPET: round2_prepare_from_partial_results/scan_tarballs_for_status_json_partial_and_write_partial_jobs_list ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From prepare_round2.sh step 1 (logic preserved; heavy but tested).
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

WORK_TMP="{{WORK_TMP:-.round2_tmp_$$}}"
mkdir -p "$WORK_TMP"
trap "rm -rf '$WORK_TMP'" EXIT

PARTIAL_LIST="$WORK_TMP/partial_jobs.txt"
> "$PARTIAL_LIST"

TOTAL_SCANNED=0
PARTIAL_COUNT=0

for SCAN_DIR in {{SCAN_DIRS}}; do
  while IFS= read -r result_tarball; do
    [ -f "$result_tarball" ] || continue
    TOTAL_SCANNED=$((TOTAL_SCANNED + 1))
    EXTRACT_DIR="$WORK_TMP/check_$TOTAL_SCANNED"
    mkdir -p "$EXTRACT_DIR"

    if tar -xzf "$result_tarball" -C "$EXTRACT_DIR" --wildcards '*/status.json' 'status.json' 2>/dev/null || \
       tar -xzf "$result_tarball" -C "$EXTRACT_DIR" status.json 2>/dev/null; then
      STATUS_FILE=$(find "$EXTRACT_DIR" -name "status.json" -type f | head -1)
      if [ -n "$STATUS_FILE" ] && [ -f "$STATUS_FILE" ]; then
        STATUS=$(grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATUS_FILE" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
        if [ "$STATUS" = "partial" ]; then
          PARTIAL_COUNT=$((PARTIAL_COUNT + 1))
          echo "$result_tarball $STATUS_FILE" >> "$PARTIAL_LIST"
        fi
      fi
    fi
    rm -rf "$EXTRACT_DIR"
  done < <(find "$SCAN_DIR" -name "*_results.tar.gz" -type f 2>/dev/null)

  while IFS= read -r backup_archive; do
    [ -f "$backup_archive" ] || continue
    INNER_RESULTS=$(tar -tzf "$backup_archive" 2>/dev/null | grep "_results\.tar\.gz$" || true)
    [ -z "$INNER_RESULTS" ] && continue

    BACKUP_EXTRACT="$WORK_TMP/backup_extract_$$"
    mkdir -p "$BACKUP_EXTRACT"
    tar -xzf "$backup_archive" -C "$BACKUP_EXTRACT" 2>/dev/null || continue

    while IFS= read -r inner_result; do
      [ -z "$inner_result" ] && continue
      INNER_PATH="$BACKUP_EXTRACT/$inner_result"
      [ -f "$INNER_PATH" ] || continue

      TOTAL_SCANNED=$((TOTAL_SCANNED + 1))
      EXTRACT_DIR="$WORK_TMP/check_inner_$TOTAL_SCANNED"
      mkdir -p "$EXTRACT_DIR"

      if tar -xzf "$INNER_PATH" -C "$EXTRACT_DIR" --wildcards '*/status.json' 'status.json' 2>/dev/null || \
         tar -xzf "$INNER_PATH" -C "$EXTRACT_DIR" status.json 2>/dev/null; then
        STATUS_FILE=$(find "$EXTRACT_DIR" -name "status.json" -type f | head -1)
        if [ -n "$STATUS_FILE" ] && [ -f "$STATUS_FILE" ]; then
          STATUS=$(grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$STATUS_FILE" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
          if [ "$STATUS" = "partial" ]; then
            PARTIAL_COUNT=$((PARTIAL_COUNT + 1))
            echo "$INNER_PATH $STATUS_FILE" >> "$PARTIAL_LIST"
          fi
        fi
      fi

      rm -rf "$EXTRACT_DIR"
    done <<< "$INNER_RESULTS"

    rm -rf "$BACKUP_EXTRACT"
  done < <(find "$SCAN_DIR" -name "backup_*.tar.gz" -type f 2>/dev/null)
done

echo "Scanned: $TOTAL_SCANNED; Partial: $PARTIAL_COUNT"
echo "Wrote: $PARTIAL_LIST"
