# ── SNIPPET: status_json_manifest/status_json_with_round2_fields_and_per_molecule_statuses ─
# Scheduler:   any
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Notes: JSON is assembled via heredoc + loop; keep formatting.
# ────────────────────────────────────────────────────────────

END_TIME=$(date +%s)
TOTAL_ELAPSED=$((END_TIME - START_TIME))

OVERALL_STATUS="complete"
if [ "$TIMEOUT_COUNT" -gt 0 ]; then
    OVERALL_STATUS="partial"
fi

COMPLETE_COUNT=0
for MOL in "${MOLECULES[@]}"; do
    s="${MOL_STATUS[$MOL]}"
    if [ "$s" = "complete" ] || [ "$s" = "complete_previous_round" ]; then
        COMPLETE_COUNT=$((COMPLETE_COUNT + 1))
    fi
done

if [ "$COMPLETE_COUNT" -eq 0 ] && [ "$PROCESSED_COUNT" -eq 0 ]; then
    OVERALL_STATUS="all_molecules_missing"
fi

cat > status.json <<STATUSEOF
{
  "zip_file": "$ZIP_FILENAME",
  "charge": "$CHARGE",
  "multiplicity": "$MULT",
  "status": "$OVERALL_STATUS",
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
    if [ $FIRST -eq 1 ]; then
        FIRST=0
    else
        echo "," >> status.json
    fi
    echo -n "    \"$MOL\": \"${MOL_STATUS[$MOL]:-unknown}\"" >> status.json
done

cat >> status.json <<STATUSEOF

  }
}
STATUSEOF
