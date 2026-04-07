# ── SNIPPET: result_packaging_tarball/pack_selected_outputs_emit_minimal_tarball_when_missing ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From run_orca_wbo.sh section 6.
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

OVERALL_STATUS="{{OVERALL_STATUS}}"
PROCESSED_COUNT={{PROCESSED_COUNT:-0}}

if [ "$OVERALL_STATUS" = "all_molecules_missing" ] && [ "$PROCESSED_COUNT" -eq 0 ]; then
  tar -czf results.tar.gz status.json
else
  find . -maxdepth 1 \( \
    -name "*.out" -o -name "*.xyz" -o -name "*.inp" -o \
    -name "*_mat.txt" -o -name "*_log.out" -o \
    -name "status.json" \
  \) -print0 | tar -czf results.tar.gz --null -T -
fi
