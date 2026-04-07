# ── SNIPPET: submission_audit_trail_pipe_log/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Log format must be: 'timestamp | job_id | rel_path | zip_path' (pipe-delimited).
# Notes: audit.sh depends on this exact delimiter and field order.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: submission_audit_trail_pipe_log.sh

SUBMIT_LOG="{{SUBMIT_LOG}}"
JOB_ID="{{JOB_ID}}"
REL_PATH="{{REL_PATH}}"
ZIP_PATH="{{ZIP_PATH}}"

echo "$(date '+%Y-%m-%d %H:%M:%S') | $JOB_ID | $REL_PATH | $ZIP_PATH" >> "$SUBMIT_LOG"
