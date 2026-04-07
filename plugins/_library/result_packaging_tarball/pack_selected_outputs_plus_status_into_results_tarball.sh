# ── SNIPPET: result_packaging_tarball/pack_selected_outputs_plus_status_into_results_tarball ─
# Scheduler:   any
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Notes: Uses tar with --null -T - for safe filenames.
# ────────────────────────────────────────────────────────────

if [ "$OVERALL_STATUS" = "all_molecules_missing" ] && [ "$PROCESSED_COUNT" -eq 0 ]; then
    tar -czf results.tar.gz status.json
else
    find . -maxdepth 1 \( \
        -name "*.out" -o -name "*.xyz" -o -name "*.inp" -o \
        -name "*_mat.txt" -o -name "*_log.out" -o \
        -name "status.json" \
    \) -print0 | tar -czf results.tar.gz --null -T -
fi
