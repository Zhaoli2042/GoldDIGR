# ── SNIPPET: workflow_bootstrap_start/append_only_chunking_with_continuous_jobN_across_batches ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From add_data.sh step 4.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

JOBS_PER_CHUNK={{JOBS_PER_CHUNK:-1000}}
SUBMITTED_DIR="{{SUBMITTED_DIR:-submitted_batches}}"
NEW_ENTRIES_FILE="{{NEW_ENTRIES_FILE}}"

[ -f "$NEW_ENTRIES_FILE" ] || { echo "Missing NEW_ENTRIES_FILE=$NEW_ENTRIES_FILE"; exit 1; }
mkdir -p "$SUBMITTED_DIR"

MAX_NUM=0
ALL_JOB_FILES=$(ls job_*.txt "$SUBMITTED_DIR"/job_*.txt 2>/dev/null || true)
for f in $ALL_JOB_FILES; do
  [ -f "$f" ] || continue
  num=$(basename "$f" | sed -n 's/^job_\([0-9]\+\)\.txt$/\1/p')
  if [ -n "$num" ] && [ "$num" -gt "$MAX_NUM" ]; then
    MAX_NUM=$num
  fi
done

NEXT_NUM=$((MAX_NUM + 1))
CHUNK_NUM=$((NEXT_NUM - 1))
LINE_NUM=0
CHUNKS_CREATED=0

while IFS= read -r line || [ -n "$line" ]; do
  if [ $((LINE_NUM % JOBS_PER_CHUNK)) -eq 0 ]; then
    CHUNK_NUM=$((CHUNK_NUM + 1))
    CHUNK_FILE="job_${CHUNK_NUM}.txt"
    > "$CHUNK_FILE"
    CHUNKS_CREATED=$((CHUNKS_CREATED + 1))
  fi
  echo "$line" >> "$CHUNK_FILE"
  LINE_NUM=$((LINE_NUM + 1))
done < "$NEW_ENTRIES_FILE"

echo "Created $CHUNKS_CREATED chunk(s): job_${NEXT_NUM}.txt → job_${CHUNK_NUM}.txt"
