# ── SNIPPET: round2_skiplist_loader/DFT-singlepoint-Anvil-Slurm_default ─
# Scheduler:   any
# Tool:        any
# Tested:      golddigr_orca_multiwfn_anvil
# Invariants:
#   - skip.txt is line-oriented; trim whitespace with xargs; ignore empty lines.
# Notes: Requires bash associative arrays.
# ────────────────────────────────────────────────────────────

#!/bin/bash
# file: round2_skiplist_loader.sh

SKIP_FILE="{{SKIP_FILE}}"   # e.g., skip.txt

declare -A SKIP_MOLECULES
if [ -f "$SKIP_FILE" ]; then
  echo "-> Found skip.txt (round-2 mode)"
  while IFS= read -r mol_name || [ -n "$mol_name" ]; do
    mol_name=$(echo "$mol_name" | xargs)
    [ -n "$mol_name" ] && SKIP_MOLECULES["$mol_name"]=1 && echo "   Skipping: $mol_name"
  done < "$SKIP_FILE"
fi
