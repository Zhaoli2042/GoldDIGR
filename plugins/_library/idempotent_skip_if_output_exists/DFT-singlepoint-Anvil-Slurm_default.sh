# ── SNIPPET: idempotent_skip_if_output_exists/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Completion is defined solely by existence of OUTPUT_ROOT/<REL_PATH>_results.tar.gz.
# Notes: Use inside submission loops to make reruns safe.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: idempotent_skip_if_output_exists.sh

OUTPUT_ROOT="{{OUTPUT_ROOT}}"
REL_PATH="{{REL_PATH}}"

FINAL_NAME="${REL_PATH}_results.tar.gz"
if [ -f "$OUTPUT_ROOT/$FINAL_NAME" ]; then
  echo "Skipping $REL_PATH: Output already exists."
  exit 0
fi

exit 1
