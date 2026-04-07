# ── SNIPPET: status_json_manifest/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - overall status is 'partial' if TIMEOUT_COUNT > 0 else 'complete'.
#   - Per-molecule statuses are string values keyed by molecule name.
# Notes: Requires bash arrays/assoc arrays in scope.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: status_json_manifest.sh

ZIP_FILENAME="{{ZIP_FILENAME}}"
COMPLETE_COUNT="{{COMPLETE_COUNT}}"
TIMEOUT_COUNT="{{TIMEOUT_COUNT}}"

# expects: MOLECULES bash array and MOL_STATUS assoc array already defined

OVERALL_STATUS="complete"
[ "$TIMEOUT_COUNT" -gt 0 ] && OVERALL_STATUS="partial"

cat > status.json <<STATUSEOF
{
  "zip_file": "$ZIP_FILENAME",
  "status": "$OVERALL_STATUS",
  "completed": $COMPLETE_COUNT,
  "timeout_skipped": $TIMEOUT_COUNT,
  "molecules": {
$(FIRST=1; for MOL in "${MOLECULES[@]}"; do
    [ $FIRST -eq 1 ] && FIRST=0 || echo ","
    echo -n "    \"$MOL\": \"${MOL_STATUS[$MOL]:-unknown}\""
done)
  }
}
STATUSEOF
