# ── SNIPPET: round2_skiplist_loader/round2_skip_contract_complete_previous_round ─
# Scheduler:   any
# Tool:        any
# Tested:      dft_energy_orca_multiwfn
# Notes: Used by run_orca_wbo.sh.
# ────────────────────────────────────────────────────────────

declare -A SKIP_MOLECULES
if [ -f "skip.txt" ]; then
    while IFS= read -r mol_name || [ -n "$mol_name" ]; do
        mol_name=$(echo "$mol_name" | xargs)
        [ -z "$mol_name" ] && continue
        SKIP_MOLECULES["$mol_name"]=1
    done < skip.txt
fi

# In loop:
if [ -n "${SKIP_MOLECULES[$MOL]+x}" ]; then
    MOL_STATUS["$MOL"]="complete_previous_round"
    continue
fi
