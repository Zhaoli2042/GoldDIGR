# ── SNIPPET: directory_structure_mirroring/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - Run from a stable SOURCE_DIR; the relative paths produced by find must be preserved.
#   - Use mkdir -p so reruns are idempotent.
# Notes: Must run on a filesystem where both SOURCE_DIR and TARGET_DIR are accessible.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: directory_structure_mirroring.sh

SOURCE_DIR="{{SOURCE_DIR}}"
TARGET_DIR="{{TARGET_DIR}}"

cd "$SOURCE_DIR" && find . -type d -exec mkdir -p "$TARGET_DIR/{}" \;
