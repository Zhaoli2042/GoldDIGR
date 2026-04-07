# ── SNIPPET: batch_submission_and_jobid_capture_slurm/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   slurm
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Assumes sbatch prints: 'Submitted batch job <id>' and job id is field 4.
# Notes: Keep awk '{print $4}' unchanged to match Slurm default message.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: batch_submission_and_jobid_capture_slurm.sh

SBATCH_SCRIPT="{{SBATCH_SCRIPT}}"
shift || true

SBATCH_OUT=$(sbatch "$SBATCH_SCRIPT" "$@")
JOB_ID=$(echo "$SBATCH_OUT" | awk '{print $4}')

echo "$JOB_ID"
