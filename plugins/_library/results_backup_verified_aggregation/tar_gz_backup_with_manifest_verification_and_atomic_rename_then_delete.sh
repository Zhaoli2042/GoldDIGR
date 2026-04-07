# ── SNIPPET: results_backup_verified_aggregation/tar_gz_backup_with_manifest_verification_and_atomic_rename_then_delete ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: Extracted from backup_results.sh create_backup().
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

RESULTS_DIR="{{RESULTS_DIR}}"
DEST_DIR="{{DEST_DIR}}"
MANIFEST_DIR="{{MANIFEST_DIR:-.backup_manifests}}"
FILE_LIST_ABS_NEWLINE="{{FILE_LIST_ABS_NEWLINE}}"

mkdir -p "$DEST_DIR" "$MANIFEST_DIR"

file_count=$(echo "$FILE_LIST_ABS_NEWLINE" | grep -c . || true)
timestamp=$(date '+%Y%m%d_%H%M%S')
backup_name="backup_${timestamp}_n${file_count}.tar.gz"
backup_tmp="$DEST_DIR/${backup_name}.tmp"
backup_final="$DEST_DIR/${backup_name}"
manifest_file="$MANIFEST_DIR/manifest_${timestamp}.txt"

echo "# Backup manifest: $backup_name" > "$manifest_file"
echo "# Created: $(date)" >> "$manifest_file"
echo "# Status: IN_PROGRESS" >> "$manifest_file"
echo "# Destination: $backup_final" >> "$manifest_file"
echo "# Files:" >> "$manifest_file"
echo "$FILE_LIST_ABS_NEWLINE" >> "$manifest_file"

# Create tar.gz preserving structure relative to RESULTS_DIR
if ! echo "$FILE_LIST_ABS_NEWLINE" | tar -czf "$backup_tmp" -C "$RESULTS_DIR" --files-from=<(
  echo "$FILE_LIST_ABS_NEWLINE" | while IFS= read -r f; do
    echo "${f#$RESULTS_DIR/}"
  done
) 2>/dev/null; then
  echo "# Status: FAILED_CREATE" >> "$manifest_file"
  rm -f "$backup_tmp"
  exit 1
fi

# Verify
if ! tar -tzf "$backup_tmp" >/dev/null 2>&1; then
  echo "# Status: FAILED_VERIFY" >> "$manifest_file"
  rm -f "$backup_tmp"
  exit 1
fi

# Atomic rename
mv "$backup_tmp" "$backup_final"

# Delete originals
deleted=0
failed=0
while IFS= read -r file; do
  [ -z "$file" ] && continue
  if rm -f "$file" 2>/dev/null; then
    deleted=$((deleted + 1))
  else
    failed=$((failed + 1))
  fi
done <<< "$FILE_LIST_ABS_NEWLINE"

find "$RESULTS_DIR" -type d -empty -delete 2>/dev/null || true

sed -i 's/IN_PROGRESS/COMPLETE/' "$manifest_file"
echo "# Completed: $(date)" >> "$manifest_file"
echo "# Deleted: $deleted, Failed: $failed" >> "$manifest_file"

echo "Backup complete: $backup_final"
