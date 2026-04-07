# ── SNIPPET: submission_log_contract_parser/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Input records are pipe-delimited: TIMESTAMP|JOB_ID|REL_PATH|ZIP_PATH.
#   - Fields may contain extra spaces; must xargs-trim REL_PATH/JOB_ID/ZIP_PATH.
# Notes: Used as a building block for audit/resubmit tooling.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: submission_log_contract_parser.sh

SUBMIT_LOG="{{SUBMIT_LOG}}"

while IFS="|" read -r TIMESTAMP JOB_ID REL_PATH ZIP_PATH; do
  REL_PATH=$(echo "$REL_PATH" | xargs)
  JOB_ID=$(echo "$JOB_ID" | xargs)
  ZIP_PATH=$(echo "$ZIP_PATH" | xargs)

  echo "$TIMESTAMP $JOB_ID $REL_PATH $ZIP_PATH"
done < "$SUBMIT_LOG"
