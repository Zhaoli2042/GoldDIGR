# ── SNIPPET: submission_manager_slurm_throttled/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   slurm
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - INPUT_LIST lines are: '<ZIP_PATH>, <REL_PATH>' with ZIP_PATH possibly ending in a comma.
#   - Completion check uses OUTPUT_ROOT/<REL_PATH>_results.tar.gz.
#   - Throttle uses squeue -u USERNAME and grep JOBNAME_GREP.
#   - Submission uses: sbatch {{SBATCH_WRAPPER}} ZIP_PATH REL_PATH OUTPUT_ROOT.
# Notes: This is the “SUBMISSION” block; it assumes an external Slurm wrapper exists.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: submission_manager_slurm_throttled.sh

MAX_JOBS="{{MAX_JOBS}}"
CHECK_DELAY="{{CHECK_DELAY}}"
INPUT_LIST="{{INPUT_LIST}}"
OUTPUT_ROOT="{{OUTPUT_ROOT}}"
SUBMIT_LOG="{{SUBMIT_LOG}}"
USERNAME="{{USERNAME}}"
JOBNAME_GREP="{{JOBNAME_GREP}}"
SBATCH_WRAPPER="{{SBATCH_WRAPPER}}"   # e.g., slurm_job.sb

mkdir -p logs
mkdir -p "$OUTPUT_ROOT"

echo "Starting manager..."
echo "Logging submissions to $SUBMIT_LOG"

while read -r ZIP_PATH REL_PATH; do
  ZIP_PATH=${ZIP_PATH%,}
  [[ "$ZIP_PATH" =~ ^#.*$ ]] && continue
  [ -z "$ZIP_PATH" ] && continue

  FINAL_NAME="${REL_PATH}_results.tar.gz"
  if [ -f "$OUTPUT_ROOT/$FINAL_NAME" ]; then
    echo "Skipping $REL_PATH: Output already exists."
    continue
  fi

  while true; do
    CURRENT_JOBS=$(squeue -u "$USERNAME" -h | grep "$JOBNAME_GREP" | wc -l)
    if [ "$CURRENT_JOBS" -lt "$MAX_JOBS" ]; then
      break
    else
      echo "Queue full ($CURRENT_JOBS/$MAX_JOBS). Waiting ${CHECK_DELAY}s..."
      sleep "$CHECK_DELAY"
    fi
  done

  echo "Submitting: $REL_PATH"
  SBATCH_OUT=$(sbatch "$SBATCH_WRAPPER" "$ZIP_PATH" "$REL_PATH" "$OUTPUT_ROOT")
  JOB_ID=$(echo "$SBATCH_OUT" | awk '{print $4}')

  echo "$(date '+%Y-%m-%d %H:%M:%S') | $JOB_ID | $REL_PATH | $ZIP_PATH" >> "$SUBMIT_LOG"
  sleep 1
done < "$INPUT_LIST"

echo "All jobs submitted."
