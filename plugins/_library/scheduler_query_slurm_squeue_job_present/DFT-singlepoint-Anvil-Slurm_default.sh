# ── SNIPPET: scheduler_query_slurm_squeue_job_present/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   slurm
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Uses: squeue -j <jobid> -h | grep -q <jobid>.
# Notes: squeue errors are suppressed to avoid noisy audits.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: scheduler_query_slurm_squeue_job_present.sh

JOB_ID="{{JOB_ID}}"

if squeue -j "$JOB_ID" -h 2>/dev/null | grep -q "$JOB_ID"; then
  exit 0
else
  exit 1
fi
