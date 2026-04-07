# ── SNIPPET: slurm_submit_throttle_by_batchtag/slurm_throttle_by_jobname_grep_polling ─
# Scheduler:   slurm
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Notes: This is intentionally coupled to a job-name pattern (e.g., 'orca_wbo').
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: queue_throttling_slurm_by_jobname.sh

USERNAME="{{USERNAME}}"
JOBNAME_GREP="{{JOBNAME_GREP}}"   # e.g., orca_wbo
MAX_JOBS="{{MAX_JOBS}}"
CHECK_DELAY="{{CHECK_DELAY}}"

while true; do
  CURRENT_JOBS=$(squeue -u "$USERNAME" -h | grep "$JOBNAME_GREP" | wc -l)

  if [ "$CURRENT_JOBS" -lt "$MAX_JOBS" ]; then
    break
  else
    echo "Queue full ($CURRENT_JOBS/$MAX_JOBS). Waiting ${CHECK_DELAY}s..."
    sleep "$CHECK_DELAY"
  fi
done
