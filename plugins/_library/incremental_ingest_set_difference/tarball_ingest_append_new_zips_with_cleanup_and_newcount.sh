# ── SNIPPET: incremental_ingest_set_difference/tarball_ingest_append_new_zips_with_cleanup_and_newcount ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From add_data.sh steps 1–3; safe to run multiple times.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

INPUTS_DIR="{{INPUTS_DIR:-inputs}}"
FILE_LIST="{{FILE_LIST:-file_list.txt}}"

# Determine tarballs to process
if [ $# -gt 0 ]; then
  INPUT_TARBALLS="$@"
else
  INPUT_TARBALLS=$(ls *.tar.gz 2>/dev/null | grep -v 'results_package' | grep -v 'backup_' || true)
fi

if [ -z "$INPUT_TARBALLS" ]; then
  echo "Error: No *.tar.gz files found."
  exit 1
fi

# Preflight
if [ ! -f "$FILE_LIST" ]; then
  echo "Error: $FILE_LIST not found. Initialize workflow first."
  exit 1
fi
if [ ! -d "$INPUTS_DIR" ] || [ ! -d "results" ]; then
  echo "Error: inputs/ or results/ directory missing. Initialize workflow first."
  exit 1
fi

# Step 1: Extract archives into inputs/
for TARBALL in $INPUT_TARBALLS; do
  if [ ! -f "$TARBALL" ]; then
    echo "Warning: $TARBALL not found, skipping"
    continue
  fi
  tar -xzf "$TARBALL" -C "$INPUTS_DIR"/
done

# Step 2: Find NEW zip files not already tracked
INPUTS_ABS="$(cd "$INPUTS_DIR" && pwd)"

ALL_ZIPS_FILE=".all_zips_$$.txt"
find "$INPUTS_ABS" -name "*.zip" -type f | sort > "$ALL_ZIPS_FILE"

TRACKED_ZIPS_FILE=".tracked_zips_$$.txt"
awk -F', ' '{print $1}' "$FILE_LIST" | sort > "$TRACKED_ZIPS_FILE"

NEW_ZIPS_FILE=".new_zips_$$.txt"
comm -23 "$ALL_ZIPS_FILE" "$TRACKED_ZIPS_FILE" > "$NEW_ZIPS_FILE"

rm -f "$ALL_ZIPS_FILE" "$TRACKED_ZIPS_FILE"

NEW_COUNT=$(wc -l < "$NEW_ZIPS_FILE")
if [ "$NEW_COUNT" -eq 0 ]; then
  echo "No new .zip files found; all zips already tracked."
  rm -f "$NEW_ZIPS_FILE"
  exit 0
fi

# Convert new zip paths to file_list format: "abspath, relpath_no_ext"
NEW_LIST_FILE=".new_entries_$$.txt"
while IFS= read -r zipfile; do
  relpath="${zipfile#$INPUTS_ABS/}"
  relpath_no_ext="${relpath%.zip}"
  echo "$zipfile, $relpath_no_ext"
done < "$NEW_ZIPS_FILE" > "$NEW_LIST_FILE"
rm -f "$NEW_ZIPS_FILE"

# Step 3: Append and mirror directories
cat "$NEW_LIST_FILE" >> "$FILE_LIST"
(cd "$INPUTS_DIR" && find . -type d -exec mkdir -p "../results/{}" \;)

rm -f "$NEW_LIST_FILE"

echo "Appended $NEW_COUNT new entries to $FILE_LIST"
