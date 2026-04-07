# ── SNIPPET: status_json_manifest/status_json_with_per_molecule_states_and_round2_detection_fields ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr
# Notes: From run_orca_wbo.sh section 5 (logic preserved).
# ────────────────────────────────────────────────────────────

#!/bin/bash
set -e

ZIP_FILENAME="{{ZIP_FILENAME}}"
CHARGE="{{CHARGE}}"
MULT="{{MULT}}"
WALL_SECONDS={{WALL_SECONDS:-70200}}
TOTAL_ELAPSED={{TOTAL_ELAPSED}}
TOTAL_MOLS={{TOTAL_MOLS}}
COMPLETE_COUNT={{COMPLETE_COUNT}}
TIMEOUT_COUNT={{TIMEOUT_COUNT}}
MISSING_COUNT={{MISSING_COUNT}}

# MOLECULES and MOL_STATUS assumed defined in caller shell

cat > status.json <<STATUSEOF
{
  "zip_file": "$ZIP_FILENAME",
  "charge": "$CHARGE",
  "multiplicity": "$MULT",
  "status": "{{OVERALL_STATUS}}",
  "wall_limit_seconds": $WALL_SECONDS,
  "elapsed_seconds": $TOTAL_ELAPSED,
  "total_molecules": $TOTAL_MOLS,
  "completed": $COMPLETE_COUNT,
  "timeout_skipped": $TIMEOUT_COUNT,
  "missing": $MISSING_COUNT,
  "molecules": {
STATUSEOF

FIRST=1
for MOL in "${MOLECULES[@]}"; do
  if [ $FIRST -eq 1 ]; then FIRST=0; else echo "," >> status.json; fi
  echo -n "    \"$MOL\": \"${MOL_STATUS[$MOL]:-unknown}\"" >> status.json
done

cat >> status.json <<STATUSEOF

  }
}
STATUSEOF
