# ── SNIPPET: directory_structure_mirroring/mirror_inputs_tree_under_results_for_remapped_outputs ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: Used in start.sh and add_data.sh.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e
INPUTS_DIR="{{INPUTS_DIR:-inputs}}"
RESULTS_DIR="{{RESULTS_DIR:-results}}"

[ -d "$INPUTS_DIR" ] || { echo "Missing $INPUTS_DIR"; exit 1; }
mkdir -p "$RESULTS_DIR"

(cd "$INPUTS_DIR" && find . -type d -exec mkdir -p "../$RESULTS_DIR/{}" \;)
echo "Mirrored $INPUTS_DIR/ -> $RESULTS_DIR/"
