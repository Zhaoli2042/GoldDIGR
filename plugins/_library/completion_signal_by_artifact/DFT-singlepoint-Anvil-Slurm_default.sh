# ── SNIPPET: completion_signal_by_artifact/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Artifact name is derived as: ${REL_PATH}_results.tar.gz.
# Notes: This is the contract shared by manager.sh and audit.sh.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: completion_signal_by_artifact.sh

OUTPUT_ROOT="{{OUTPUT_ROOT}}"
REL_PATH="{{REL_PATH}}"

FINAL_NAME="${REL_PATH}_results.tar.gz"
[ -f "$OUTPUT_ROOT/$FINAL_NAME" ]
