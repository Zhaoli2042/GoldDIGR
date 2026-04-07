# ── SNIPPET: audit_submitted_jobs_slurm/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   slurm
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Reads SUBMIT_LOG with pipe-delimited contract.
#   - Completion is OUTPUT_ROOT/<REL_PATH>_results.tar.gz.
#   - If artifact missing and job not in squeue => mark FAILED and write '<ZIP_PATH> <REL_PATH>'.
# Notes: This is the “HEALTH MONITOR” block for the workflow (detect failed/crashed).
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: audit_submitted_jobs_slurm.sh

OUTPUT_ROOT="{{OUTPUT_ROOT}}"
SUBMIT_LOG="{{SUBMIT_LOG}}"
FAILED_LOG="{{FAILED_LOG}}"

echo "Auditing submitted jobs..."

> "$FAILED_LOG"

while IFS="|" read -r TIMESTAMP JOB_ID REL_PATH ZIP_PATH; do
  REL_PATH=$(echo "$REL_PATH" | xargs)
  JOB_ID=$(echo "$JOB_ID" | xargs)
  ZIP_PATH=$(echo "$ZIP_PATH" | xargs)

  FINAL_NAME="${REL_PATH}_results.tar.gz"

  if [ ! -f "$OUTPUT_ROOT/$FINAL_NAME" ]; then
    if squeue -j "$JOB_ID" -h 2>/dev/null | grep -q "$JOB_ID"; then
      echo "-> Job $JOB_ID ($REL_PATH) is still RUNNING or PENDING."
    else
      echo "-> FAILED/CRASHED: Job $JOB_ID ($REL_PATH)"
      echo "$ZIP_PATH $REL_PATH" >> "$FAILED_LOG"
    fi
  fi
done < "$SUBMIT_LOG"

echo "----------------------------------------"
echo "Audit complete."
echo "Any crashed/failed jobs have been written to $FAILED_LOG."
