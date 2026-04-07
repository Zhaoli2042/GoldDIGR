# ── SNIPPET: slurm_submit_throttle_by_batchtag/htcondor_dripfeed_chunk_submission_with_max_queue_and_move_to_submitted ─
# Scheduler:   htcondor
# Tool:        any
# Tested:      golddigr
# Notes: monitor_submit.sh as-is.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

MAX_JOBS={{MAX_JOBS:-100000}}
USER_ID="${USER}"
CHECK_INTERVAL={{CHECK_INTERVAL:-300}}
SUBMIT_FILE="{{SUBMIT_FILE:-batch_job.submit}}"
FILE_PATTERN="{{FILE_PATTERN:-job_*.txt}}"

mkdir -p submitted_batches

get_job_count() {
  local count
  count=$(condor_q "$USER_ID" 2>/dev/null | grep "Total for query" | awk '{print $4}')
  if [ -z "$count" ]; then
    count=$(condor_q "$USER_ID" 2>/dev/null | awk -v user="$USER_ID" '$0 ~ user {sum += $10} END {print sum+0}')
  fi
  echo "${count:-0}"
}

[ -f "$SUBMIT_FILE" ] || { echo "Error: Submit file not found: $SUBMIT_FILE"; exit 1; }

PENDING_FILES=$(ls $FILE_PATTERN 2>/dev/null | wc -l)
[ "$PENDING_FILES" -gt 0 ] || { echo "Error: No job files found matching $FILE_PATTERN"; exit 1; }

for batch_file in $(ls $FILE_PATTERN 2>/dev/null | sort -t_ -k2 -n); do
  [ -f "$batch_file" ] || continue

  if [ -f "submitted_batches/$batch_file" ]; then
    echo "Skipping $batch_file (already submitted)"
    continue
  fi

  while true; do
    current_jobs=$(get_job_count)
    echo "[$(date '+%H:%M:%S')] Queue: $current_jobs / $MAX_JOBS jobs"
    if [ "$current_jobs" -lt "$MAX_JOBS" ]; then
      echo "   -> Queue has capacity. Submitting..."
      break
    else
      echo "   -> Queue full. Waiting $((CHECK_INTERVAL / 60)) minutes..."
      sleep $CHECK_INTERVAL
    fi
  done

  JOB_COUNT=$(wc -l < "$batch_file")
  echo "Submitting: $batch_file ($JOB_COUNT jobs)"
  condor_submit "$SUBMIT_FILE" input_list="$batch_file"
  SUBMIT_EXIT=$?

  if [ $SUBMIT_EXIT -eq 0 ]; then
    mv "$batch_file" submitted_batches/
  else
    echo "Warning: condor_submit returned exit code $SUBMIT_EXIT; will retry"
    sleep 60
    continue
  fi

  sleep 10
done

echo "All job files submitted!"
