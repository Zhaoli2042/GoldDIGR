# ── SNIPPET: failure_list_for_retry/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Each line must be: ZIP_PATH<space>REL_PATH (no pipes, no commas).
# Notes: audit.sh writes this for downstream resubmission tooling.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: failure_list_for_retry.sh

FAILED_LOG="{{FAILED_LOG}}"
ZIP_PATH="{{ZIP_PATH}}"
REL_PATH="{{REL_PATH}}"

echo "$ZIP_PATH $REL_PATH" >> "$FAILED_LOG"
